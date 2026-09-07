"""Owned local process lifecycle for managed inference servers."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import psutil

from ..errors import LLMRuntimeError, RuntimeErrorCode


class ProcessMode(StrEnum):
    EXTERNAL = "EXTERNAL"
    MANAGED = "MANAGED"


class ProcessState(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    EXITED = "EXITED"
    STOPPING = "STOPPING"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ExternalProcessBinding:
    """Configuration for either an external endpoint or a managed process."""

    mode: ProcessMode = ProcessMode.EXTERNAL
    command: tuple[str, ...] = ()
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    endpoint: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None


class ManagedProcess:
    """Start and stop exactly one process tree that this instance created.

    Ownership is established with the child PID and its creation time. Stop
    never searches by executable name and never issues a broad task-kill.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        stdout_path: str | Path | None = None,
        stderr_path: str | Path | None = None,
        endpoint: str | None = None,
    ) -> None:
        if not command or any(not isinstance(part, str) or not part for part in command):
            raise ValueError("managed process command must be a non-empty string sequence")
        self.command = tuple(command)
        self.cwd = str(Path(cwd).resolve()) if cwd is not None else None
        self.env = dict(env or {})
        self.stdout_path = Path(stdout_path).resolve() if stdout_path is not None else None
        self.stderr_path = Path(stderr_path).resolve() if stderr_path is not None else None
        self.endpoint = endpoint
        self.state = ProcessState.STOPPED
        self._process: subprocess.Popen[bytes] | None = None
        self._stdout_file = None
        self._stderr_file = None
        self._pid: int | None = None
        self._create_time: float | None = None
        self._started_at: float | None = None

    @property
    def pid(self) -> int | None:
        return self._pid

    @property
    def returncode(self) -> int | None:
        return self._process.returncode if self._process is not None else None

    def start(self) -> int:
        if self.is_running():
            assert self._pid is not None
            return self._pid
        self.state = ProcessState.STARTING
        try:
            self._open_log_files()
            process_env = os.environ.copy()
            process_env.update(self.env)
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            self._process = subprocess.Popen(
                list(self.command),
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=self._stdout_file or subprocess.DEVNULL,
                stderr=self._stderr_file or subprocess.DEVNULL,
                cwd=self.cwd,
                env=process_env,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
            self._pid = int(self._process.pid)
            self._create_time = psutil.Process(self._pid).create_time()
            self._started_at = time.time()
            self.state = ProcessState.RUNNING if self.is_running() else ProcessState.EXITED
            return self._pid
        except (OSError, psutil.Error, ValueError) as exc:
            self.state = ProcessState.FAILED
            self._close_log_files()
            raise LLMRuntimeError(
                RuntimeErrorCode.PROCESS_START_FAILED,
                "Managed inference process could not be started.",
                details={"exception": type(exc).__name__},
            ) from exc

    def is_running(self) -> bool:
        if self._process is None or self._pid is None:
            return False
        if self._process.poll() is not None:
            self.state = ProcessState.EXITED
            return False
        try:
            process = psutil.Process(self._pid)
            if (
                self._create_time is not None
                and abs(process.create_time() - self._create_time) > 0.01
            ):
                self.state = ProcessState.FAILED
                return False
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except psutil.Error:
            self.state = ProcessState.EXITED
            return False

    def metadata(self) -> dict[str, object]:
        return {
            "mode": ProcessMode.MANAGED.value,
            "state": self.state.value,
            "pid": self._pid,
            "create_time": self._create_time,
            "started_at": self._started_at,
            "command": list(self.command),
            "cwd": self.cwd,
            "endpoint": self.endpoint,
            "owned": True,
            "returncode": self.returncode,
        }

    def stop(self, *, timeout_seconds: float = 10.0) -> bool:
        if self._process is None or self._pid is None:
            self.state = ProcessState.STOPPED
            self._close_log_files()
            return True
        if not self._matches_owned_process():
            if self._process.poll() is None:
                self.state = ProcessState.FAILED
                raise LLMRuntimeError(
                    RuntimeErrorCode.PROCESS_STOP_FAILED,
                    "Managed process identity changed; refusing to terminate an unowned PID.",
                    details={"pid": self._pid},
                )
            self.state = ProcessState.STOPPED
            self._close_log_files()
            return True

        self.state = ProcessState.STOPPING
        try:
            root = psutil.Process(self._pid)
            descendants = root.children(recursive=True)
            targets = [*reversed(descendants), root]
            for process in targets:
                try:
                    process.terminate()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs(targets, timeout=max(float(timeout_seconds), 0.05))
            for process in alive:
                try:
                    process.kill()
                except psutil.NoSuchProcess:
                    pass
            if alive:
                _, still_alive = psutil.wait_procs(
                    alive,
                    timeout=min(2.0, max(float(timeout_seconds), 0.05)),
                )
                if still_alive:
                    self.state = ProcessState.FAILED
                    raise LLMRuntimeError(
                        RuntimeErrorCode.PROCESS_STOP_FAILED,
                        "Managed process tree did not stop within the bounded timeout.",
                        details={"pid": self._pid, "alive_pids": [p.pid for p in still_alive]},
                    )
            self._process.wait(timeout=max(float(timeout_seconds), 0.05))
            self.state = ProcessState.STOPPED
            return True
        except LLMRuntimeError:
            raise
        except (psutil.Error, subprocess.TimeoutExpired, OSError) as exc:
            self.state = ProcessState.FAILED
            raise LLMRuntimeError(
                RuntimeErrorCode.PROCESS_STOP_FAILED,
                "Managed inference process could not be stopped safely.",
                details={"pid": self._pid, "exception": type(exc).__name__},
            ) from exc
        finally:
            self._close_log_files()

    def _matches_owned_process(self) -> bool:
        if self._pid is None or self._create_time is None:
            return False
        try:
            process = psutil.Process(self._pid)
            return abs(process.create_time() - self._create_time) <= 0.01
        except psutil.Error:
            return False

    def _open_log_files(self) -> None:
        try:
            if self.stdout_path is not None:
                self.stdout_path.parent.mkdir(parents=True, exist_ok=True)
                self._stdout_file = self.stdout_path.open("ab")
            if self.stderr_path is not None:
                self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
                self._stderr_file = self.stderr_path.open("ab")
        except OSError:
            self._close_log_files()
            raise

    def _close_log_files(self) -> None:
        for stream_name in ("_stdout_file", "_stderr_file"):
            stream = getattr(self, stream_name)
            if stream is not None:
                try:
                    stream.close()
                finally:
                    setattr(self, stream_name, None)

    def __enter__(self) -> ManagedProcess:
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()
