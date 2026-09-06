"""Conservative host hardware detection with no synthetic GPU fallback."""

from __future__ import annotations

import ctypes
import os
import platform
import re
import shutil
import subprocess
from typing import Any

from ..domain.models import GPUInfo, HardwareInfo


class HardwareDetector:
    def detect(self) -> HardwareInfo:
        gpu_rows, smi_path, gpu_error = self._detect_nvidia()
        return HardwareInfo(
            os=f"{platform.system()} {platform.release()} ({platform.machine()})",
            cpu=platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
            threads=os.cpu_count() or 1,
            ram_bytes=self._total_memory_bytes(),
            gpu_present=bool(gpu_rows),
            gpus=tuple(gpu_rows),
            cuda_available=bool(gpu_rows),
            nvidia_smi_path=smi_path,
            detection_error=gpu_error,
        )

    @staticmethod
    def _detect_nvidia() -> tuple[list[GPUInfo], str | None, str | None]:
        executable = shutil.which("nvidia-smi")
        if not executable:
            return [], None, "nvidia-smi not found"
        command = [
            executable,
            "--query-gpu=name,memory.total,driver_version,cuda_version",
            "--format=csv,noheader,nounits",
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return [], executable, f"nvidia-smi unavailable: {type(exc).__name__}"
        if result.returncode != 0:
            message = (result.stderr or result.stdout or f"exit code {result.returncode}").strip()
            return [], executable, f"nvidia-smi failed: {message[:300]}"
        gpus: list[GPUInfo] = []
        for row in result.stdout.splitlines():
            values = [part.strip() for part in row.split(",")]
            if len(values) < 4 or not values[0]:
                continue
            vram_mib = _parse_number(values[1])
            gpus.append(
                GPUInfo(
                    name=values[0],
                    vram_bytes=int(vram_mib * 1024 * 1024) if vram_mib is not None else None,
                    driver=values[2] or None,
                    cuda_version=values[3] or None,
                )
            )
        return gpus, executable, None if gpus else "nvidia-smi returned no GPU rows"

    @staticmethod
    def _total_memory_bytes() -> int | None:
        if platform.system() == "Windows":
            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(MemoryStatusEx)
            try:
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                    return int(status.ullTotalPhys)
            except AttributeError:
                return None
        try:
            for line in open("/proc/meminfo", encoding="utf-8"):
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
        except (FileNotFoundError, OSError, ValueError):
            return None
        return None


def _parse_number(value: str) -> float | None:
    match = re.search(r"[0-9]+(?:\.[0-9]+)?", value)
    return float(match.group(0)) if match else None

