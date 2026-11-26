"""Bound the public demo's optional, private formula recognition process."""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from smhai_backend.core.errors import ErrorCode, error

from .workspace_agent_formula_worker import MAX_BYTES as MAX_BYTES

FORMULA_SLOTS = asyncio.Semaphore(1)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def extract_formula(content: bytes) -> str:
    directory = os.environ.get("SMHAI_DEMO_FORMULA_DIRECTORY")
    if not directory:
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="formula recognition is unavailable")
    root = Path(directory)
    interpreter = root / "venv" / "bin" / "python"
    worker = Path(__file__).with_name("workspace_agent_formula_worker.py")
    model = root / "model"
    if not interpreter.is_file() or not model.is_dir():
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="formula recognition is unavailable")

    try:
        result = subprocess.run(
            [str(interpreter), "-I", str(worker), str(model)], input=content,
            capture_output=True, timeout=18, check=False,
            env={"LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.TimeoutExpired):
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE, detail="formula processing could not finish"
        ) from None
    if result.returncode not in (0, 2):
        raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="formula recognition is unavailable")
    if result.returncode != 0 or not 1 <= len(result.stdout) <= 2_800:
        raise error(ErrorCode.VALIDATION_FAILED, detail="could not read formula")
    return result.stdout.decode("utf-8")
