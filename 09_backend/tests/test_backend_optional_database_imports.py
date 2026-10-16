"""A clean Backend install must import without the separate database environment."""

import subprocess
import sys
from pathlib import Path


def test_app_factory_import_does_not_require_sqlalchemy() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src"
    script = f"""
import importlib.abc
import sys
sys.path.insert(0, {str(source_root)!r})

class NoDatabaseImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'sqlalchemy' or fullname.startswith('sqlalchemy.'):
            raise ModuleNotFoundError('database runtime is intentionally unavailable')
        return None

sys.meta_path.insert(0, NoDatabaseImports())
import smhai_backend.app_factory
assert 'sqlalchemy' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
