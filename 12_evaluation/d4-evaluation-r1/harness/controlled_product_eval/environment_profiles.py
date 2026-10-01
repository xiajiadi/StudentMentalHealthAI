"""Pinned task-local Python environments for the D4-3B managed runner."""

from pathlib import Path


D4_TASK_TOOLS_ROOT = Path(r"D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run")
GIT_EXECUTABLE = Path(r"D:\Software\Git\cmd\git.exe")
BACKEND_PYTHON = (
    D4_TASK_TOOLS_ROOT / "venvs" / "backend-formal-r2" / "Scripts" / "python.exe"
)
RAG_PYTHON = (
    D4_TASK_TOOLS_ROOT / "venvs" / "rag-env-lock-r1" / "Scripts" / "python.exe"
)
MYSQL_BASEDIR = Path(r"D:\Software\MySQLServer8.4")
MYSQLD_EXECUTABLE = MYSQL_BASEDIR / "bin" / "mysqld.exe"
MYSQL_VERSION = "8.4.8"
