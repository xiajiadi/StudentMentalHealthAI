"""Pinned task-local Python environments for the D4-3B managed runner."""

from pathlib import Path


D4_TASK_TOOLS_ROOT = Path(r"D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run")
BACKEND_PYTHON = (
    D4_TASK_TOOLS_ROOT / "venvs" / "backend-formal-r2" / "Scripts" / "python.exe"
)
RAG_PYTHON = (
    D4_TASK_TOOLS_ROOT / "venvs" / "rag-env-lock-r1" / "Scripts" / "python.exe"
)
