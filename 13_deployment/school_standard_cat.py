"""Pins and process arguments for the optional synthetic standard CAT service."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STANDARD_CAT_PORT = 8180
STANDARD_CAT_MODULE = "cat_engine.api.app"
STANDARD_CAT_CONFIG_RELATIVE = Path("01_cat-engine/fixtures/demo_cat_config.v1.json")
STANDARD_CAT_BANK_RELATIVE = Path(
    "01_cat-engine/fixtures/synthetic_item_bank.v1.json"
)
STANDARD_CAT_SOURCE_RELATIVE = Path("01_cat-engine/src/cat_engine")
STANDARD_CAT_ENTRYPOINT_RELATIVE = Path("01_cat-engine/src/cat_engine/api/app.py")
STANDARD_CAT_PROJECT_FILE = Path("01_cat-engine/pyproject.toml")
STANDARD_CAT_PYTHON_RELATIVE = Path("01_cat-engine/.venv/Scripts/python.exe")
STANDARD_CAT_SOURCE_SHA256 = "a0b72c364690e0a353273d8c452dd7884a46225a9aa2de0c31d97ae7ab8db56c"
STANDARD_CAT_ENTRYPOINT_SHA256 = "89fb5d31ca74d947ae092a62cb0019a565125894092219925cd7ca88d9a5f697"
STANDARD_CAT_CONFIG_SHA256 = "78f9922930e40a8f9f8c436a644e5c7b9548d9d4f32377d30f143619f3f09e8a"
STANDARD_CAT_BANK_SHA256 = "e73d4d8f3732d690f0b248f28ff19b6bbabbb7f8834abf2a57a4d0ba3353585e"
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class StandardCATError(RuntimeError):
    """Closed diagnostic for pinned standard CAT preflight failures."""


@dataclass(frozen=True, slots=True)
class StandardCATConfig:
    port: int
    python: Path
    module: str
    config_file: Path
    config_sha256: str
    item_bank_file: Path
    item_bank_sha256: str
    source_sha256: str

    def manifest_value(self) -> dict[str, object]:
        return {
            "enabled": True,
            "port": self.port,
            "python": str(self.python),
            "module": self.module,
            "config_file": str(self.config_file),
            "config_sha256": self.config_sha256,
            "item_bank_file": str(self.item_bank_file),
            "item_bank_sha256": self.item_bank_sha256,
            "source_sha256": self.source_sha256,
        }

    def argv(self) -> list[str]:
        return [str(self.python), "-m", self.module]

    def environment(self) -> dict[str, str]:
        source_root = self.python.parents[2] / "src"
        return {
            "PYTHONPATH": str(source_root),
            "SMHAI_CAT_PORT": str(self.port),
            "SMHAI_CAT_CONFIG": str(self.config_file),
            "SMHAI_CAT_ITEM_BANK": str(self.item_bank_file),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return True
    return path.is_symlink() or bool(
        getattr(info, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT
    )


def source_fingerprint(repo: Path) -> str:
    """Hash the complete CAT Python package and packaging metadata deterministically."""
    root = repo / STANDARD_CAT_SOURCE_RELATIVE
    project_file = repo / STANDARD_CAT_PROJECT_FILE
    files = sorted(root.rglob("*.py")) + [project_file]
    if (
        not root.is_dir()
        or _is_reparse_or_symlink(root)
        or not project_file.is_file()
        or _is_reparse_or_symlink(project_file)
        or not files
    ):
        raise StandardCATError("Pinned CAT source is unavailable")
    digest = hashlib.sha256()
    for path in files:
        if _is_reparse_or_symlink(path) or not path.is_file():
            raise StandardCATError("Pinned CAT source contains an unsafe path")
        if not path.resolve(strict=True).is_relative_to(repo.resolve(strict=True)):
            raise StandardCATError("Pinned CAT source escaped the repository")
        relative = path.relative_to(repo).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def load_standard_cat_config(repo: Path, port: int) -> StandardCATConfig:
    """Verify the exact project-local interpreter, CAT source and synthetic assets."""
    if type(port) is not int or not 1024 <= port <= 65535:
        raise StandardCATError("Standard CAT port is invalid")
    repo = repo.resolve(strict=True)
    python = repo / STANDARD_CAT_PYTHON_RELATIVE
    config_file = repo / STANDARD_CAT_CONFIG_RELATIVE
    item_bank_file = repo / STANDARD_CAT_BANK_RELATIVE
    entrypoint = repo / STANDARD_CAT_ENTRYPOINT_RELATIVE
    required = (python, config_file, item_bank_file, entrypoint)
    if any(not path.is_file() or _is_reparse_or_symlink(path) for path in required):
        raise StandardCATError("Pinned standard CAT assets are unavailable")
    try:
        config_hash = _sha256(config_file)
        bank_hash = _sha256(item_bank_file)
        entrypoint_hash = _sha256(entrypoint)
        source_hash = source_fingerprint(repo)
    except OSError:
        raise StandardCATError("Pinned standard CAT assets could not be read") from None
    if (
        config_hash != STANDARD_CAT_CONFIG_SHA256
        or bank_hash != STANDARD_CAT_BANK_SHA256
        or entrypoint_hash != STANDARD_CAT_ENTRYPOINT_SHA256
        or source_hash != STANDARD_CAT_SOURCE_SHA256
    ):
        raise StandardCATError("Pinned standard CAT source or assets changed")
    return StandardCATConfig(
        port=port,
        python=python,
        module=STANDARD_CAT_MODULE,
        config_file=config_file,
        config_sha256=config_hash,
        item_bank_file=item_bank_file,
        item_bank_sha256=bank_hash,
        source_sha256=source_hash,
    )


def restore_standard_cat_config(
    repo: Path, value: object
) -> StandardCATConfig:
    if type(value) is not dict or set(value) != {
        "enabled",
        "port",
        "python",
        "module",
        "config_file",
        "config_sha256",
        "item_bank_file",
        "item_bank_sha256",
        "source_sha256",
    }:
        raise StandardCATError("Lifecycle standard CAT configuration is invalid")
    if value.get("enabled") is not True or type(value.get("port")) is not int:
        raise StandardCATError("Lifecycle standard CAT configuration is invalid")
    try:
        config = load_standard_cat_config(repo, value["port"])
    except (OSError, ValueError, StandardCATError):
        raise StandardCATError("Lifecycle standard CAT pins failed validation") from None
    if config.manifest_value() != value:
        raise StandardCATError("Lifecycle standard CAT pins changed")
    return config
