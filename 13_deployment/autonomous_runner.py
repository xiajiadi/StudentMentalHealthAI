"""Project-scoped task leases and recovery; never an unattended model loop.

No database access, service control, credential loading or arbitrary shell commands.
Durable task specification is tracked; local execution state is ignored.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import hashlib
import os
from pathlib import Path
import re
import time
import subprocess
from typing import Iterator

STATES = {"BACKLOG", "READY", "IN_PROGRESS", "REVIEW", "TESTING", "INTEGRATING", "DONE", "BLOCKED", "DEFERRED"}
NAME = re.compile(r"^[A-Za-z0-9_/-]{1,100}$")


class TaskError(ValueError):
    pass


class Runner:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.queue_path = self.root / "14_docs/autonomous-delivery/TASK_QUEUE.json"
        if not self.queue_path.is_file():
            raise TaskError("Task queue missing in selected project")
        self.local = self.root / ".autonomous"
        if self.local.is_symlink():
            raise TaskError("Local state directory must not be a symlink")
        self.local.mkdir(exist_ok=True)
        if self.local.resolve().parent != self.root:
            raise TaskError("Local state escapes project")
        self.state_path = self.local / "state.json"

    @contextmanager
    def locked(self) -> Iterator[None]:
        # Kernel advisory locks are released on process exit, including a crash.
        # Keep the inode/file: unlinking it could create two distinct lock targets.
        lock = self.local / "runner.lock"
        if lock.is_symlink():
            raise TaskError("Lock must not be a symlink")
        with lock.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise TaskError("Runner busy") from exc
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def load(self) -> dict:
        spec = json.loads(self.queue_path.read_text(encoding="utf-8"))
        definition_hash = hashlib.sha256(self.queue_path.read_bytes()).hexdigest()
        ids = [t["id"] for t in spec["tasks"]]
        if len(set(ids)) != len(ids):
            raise TaskError("Duplicate task IDs")
        for task in spec["tasks"]:
            if task["status"] not in STATES or not set(task["depends_on"]).issubset(ids):
                raise TaskError("Invalid task state/dependencies")
        if self.state_path.exists():
            runtime = json.loads(self.state_path.read_text(encoding="utf-8"))
            if runtime.get("definition_hash") != definition_hash:
                raise TaskError("Queue changed; explicit state migration required")
            current = {t["id"]: t for t in runtime["tasks"]}
            spec["tasks"] = [current.get(t["id"], t) for t in spec["tasks"]]
            spec["stopped"] = runtime.get("stopped", False)
        spec["definition_hash"] = definition_hash
        return spec

    def head(self) -> str:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True, check=True, timeout=10)
        return result.stdout.strip()

    def require_clean(self, state: dict) -> None:
        result = subprocess.run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=self.root, capture_output=True, check=True, timeout=10)
        allowed = state.get("baseline_untracked_artifacts", [])
        for entry in result.stdout.decode("utf-8").split("\0"):
            if not entry:
                continue
            status, path = entry[:2], entry[3:]
            if status == "??" and any(path == item or (item.endswith("/") and path.startswith(item)) for item in allowed):
                continue
            raise TaskError("Commit all task changes before DONE; preserve baseline artifacts")

    def fresh_pass(self, task: dict, owner: str) -> bool:
        records = [e for e in task["evidence"] if e.get("attempt") == task["attempts"] and e.get("owner") == owner]
        if not records or records[-1]["outcome"] != "pass":
            return False
        record = records[-1]
        target = self.root / record["path"]
        return target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == record["sha256"] and record["commit"] == self.head()

    def save(self, state: dict) -> None:
        temp = self.local / "state.tmp"
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, self.state_path)

    def sync_queue(self) -> dict:
        """Explicitly reconcile edited definitions; invalidate dependent acceptance."""
        with self.locked():
            spec = json.loads(self.queue_path.read_text(encoding="utf-8"))
            runtime = json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists() else None
            if runtime:
                if runtime["baseline"] != spec["baseline"]:
                    raise TaskError("Baseline migration requires separate reviewed tooling")
                if any(t.get("owner") and t.get("lease_until", 0) > time.time() for t in runtime["tasks"]):
                    raise TaskError("Release active tasks before changing queue definitions")
                old = {t["id"]: t for t in runtime["tasks"]}
                changed = {t["id"] for t in spec["tasks"] if t["id"] not in old or any(t.get(key) != old[t["id"]].get(key) for key in ("title", "priority", "depends_on", "acceptance"))}
                while True:
                    expanded = changed | {t["id"] for t in spec["tasks"] if set(t["depends_on"]) & changed}
                    if expanded == changed:
                        break
                    changed = expanded
                spec["tasks"] = [t if t["id"] in changed else old.get(t["id"], t) for t in spec["tasks"]]
                spec["stopped"] = runtime.get("stopped", False)
            ids = [t["id"] for t in spec["tasks"]]
            if len(ids) != len(set(ids)) or any(not set(t["depends_on"]).issubset(ids) for t in spec["tasks"]):
                raise TaskError("Invalid queue definitions")
            spec["definition_hash"] = hashlib.sha256(self.queue_path.read_bytes()).hexdigest()
            self.save(spec)
            return spec

    @staticmethod
    def task(state: dict, task_id: str) -> dict:
        for task in state["tasks"]:
            if task["id"] == task_id:
                return task
        raise TaskError("Unknown task")

    @staticmethod
    def eligible(state: dict, task: dict) -> bool:
        done = {t["id"] for t in state["tasks"] if t["status"] == "DONE"}
        return task["status"] in {"READY", "BACKLOG"} and set(task["depends_on"]).issubset(done)

    def mutate(self, action: str, task_id: str = "", owner: str = "", evidence: str = "", outcome: str = "", lease_seconds: int = 5400, command: str = "") -> dict:
        if owner and not NAME.fullmatch(owner):
            raise TaskError("Use an agent identifier, not free-form text")
        with self.locked():
            state = self.load()
            if action in {"stop", "resume"}:
                state["stopped"] = action == "stop"
            elif action == "recover":
                for task in state["tasks"]:
                    if task["status"] in {"IN_PROGRESS", "TESTING", "INTEGRATING"} and task.get("lease_until", 0) <= time.time():
                        task["status"] = "REVIEW" if task["evidence"] else "READY"
                        task["owner"] = None
                        task["lease_until"] = 0
            else:
                if state.get("stopped"):
                    raise TaskError("Runner stopped")
                task = self.task(state, task_id)
                if action == "claim":
                    if not owner or not self.eligible(state, task):
                        raise TaskError("Task unavailable or dependencies incomplete")
                    if task["attempts"] >= state["max_attempts"]:
                        raise TaskError("Attempt limit reached")
                    task.update(status="IN_PROGRESS", author=owner, owner=owner, reviewer=None, lease_until=time.time() + lease_seconds)
                    task["attempts"] += 1
                elif action == "review":
                    if not owner or owner == task.get("author") or task["status"] != "REVIEW" or task.get("owner") not in {None, owner}:
                        raise TaskError("Independent review requires a different owner and REVIEW state")
                    if not self.fresh_pass(task, task["author"]):
                        raise TaskError("Successful verification evidence required")
                    task["reviewer"] = owner
                    task["status"] = "INTEGRATING"
                    task["owner"] = owner
                    task["lease_until"] = time.time() + lease_seconds
                elif action == "reject":
                    if not owner or owner == task.get("author") or task["status"] != "REVIEW":
                        raise TaskError("Independent reviewer can reject only REVIEW")
                    task.update(status="BLOCKED" if task["attempts"] >= state["max_attempts"] else "READY", owner=None, lease_until=0)
                else:
                    if not owner or task.get("owner") != owner or task.get("lease_until", 0) <= time.time():
                        raise TaskError("Active owner lease required")
                    if action == "checkpoint":
                        task["lease_until"] = time.time() + lease_seconds
                    elif action == "evidence":
                        target = (self.root / evidence).resolve()
                        if not evidence or Path(evidence).is_absolute() or not target.is_relative_to(self.root) or not target.is_file():
                            raise TaskError("Evidence must be an existing project-relative file")
                        if outcome not in {"pass", "fail"}:
                            raise TaskError("Evidence outcome must be pass/fail")
                        if not command or len(command) > 200 or not re.fullmatch(r"[A-Za-z0-9_ ./:-]+", command):
                            raise TaskError("Record a non-sensitive verification command identifier")
                        task["evidence"].append({"path": target.relative_to(self.root).as_posix(), "outcome": outcome, "owner": owner, "at": time.time(), "attempt": task["attempts"], "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "commit": self.head(), "command": command})
                    elif action == "submit":
                        if task["status"] != "IN_PROGRESS" or not self.fresh_pass(task, owner):
                            raise TaskError("Submit requires implementation and evidence")
                        task.update(status="REVIEW", author=owner, owner=None, lease_until=0)
                    elif action == "done":
                        if task["status"] != "INTEGRATING" or task.get("reviewer") != owner:
                            raise TaskError("Independent review/integration required")
                        if not self.fresh_pass(task, owner) or not self.fresh_pass(task, task["author"]):
                            raise TaskError("Reviewer integration evidence required")
                        self.require_clean(state)
                        task.update(status="DONE", owner=None, lease_until=0, commits=[self.head()])
                    elif action == "fail":
                        task.update(status="BLOCKED" if task["attempts"] >= state["max_attempts"] else "READY", owner=None, lease_until=0)
                    else:
                        raise TaskError("Unknown action")
            self.save(state)
            return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "ready", "sync", "claim", "checkpoint", "evidence", "submit", "review", "reject", "done", "fail", "recover", "stop", "resume"])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--task", default="")
    parser.add_argument("--owner", default="")
    parser.add_argument("--evidence", default="")
    parser.add_argument("--outcome", choices=["pass", "fail"], default="")
    parser.add_argument("--command", default="")
    args = parser.parse_args()
    try:
        runner = Runner(args.root)
        if args.action in {"status", "ready"}:
            state = runner.load()
        elif args.action == "sync":
            state = runner.sync_queue()
        else:
            state = runner.mutate(args.action, args.task, args.owner, args.evidence, args.outcome, command=args.command)
        tasks = state["tasks"]
        if args.action == "ready":
            tasks = [] if state.get("stopped") else sorted([t for t in tasks if runner.eligible(state, t)], key=lambda t: -t["priority"])
        print(json.dumps({"baseline": state["baseline"], "stopped": state.get("stopped", False), "tasks": [{k: t.get(k) for k in ("id", "status", "owner", "attempts")} for t in tasks]}, ensure_ascii=False, indent=2))
        return 0
    except (TaskError, OSError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        # File paths/free-form exception messages may contain private local context.
        print(f"Runner failed: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
