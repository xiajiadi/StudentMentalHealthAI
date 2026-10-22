"""Build a deterministic, secret-free bundle for the pinned Linux CAT service."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

SOURCE_COMMIT = "b7773176acd151f4a2cb7110a43162719a4f8c2a"
PYTHON_VERSION = "3.14.6"
CAT_SOURCE_SHA256 = "eb993e7c3de8d61a101e3a9d7787ebb6e204ea02071f2361372267d0cf15995e"
CAT_ENTRYPOINT_SHA256 = "f92345a15666241490d87e1dfbedbbce771e99e6f51d5bc2eb71e4849631c490"
CAT_CONFIG_SHA256 = "e7da9e073f2cc5fc5ed28c4118c456feda0b798866ea3ca8623193f0224be8a4"
CAT_BANK_SHA256 = "250fa3f9868c73e2e1c962ffb78e0308d8d13e8144168ac19edfb7174da9fa56"


class BundleError(ValueError):
    """Raised when a pinned CAT source commit cannot produce a safe bundle."""


def _git(repo: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        raise BundleError("git_command_failed") from None
    if result.returncode:
        raise BundleError("git_object_unavailable")
    return result.stdout


def _source_paths(repo: Path) -> list[str]:
    tracked = _git(repo, "ls-tree", "-r", "--name-only", SOURCE_COMMIT).decode(
        "utf-8", errors="strict"
    ).splitlines()
    fixed = {
        "01_cat-engine/ADAPTIVETESTING_COMPATIBILITY_REPORT.md",
        "01_cat-engine/README.md",
        "01_cat-engine/pyproject.toml",
        "01_cat-engine/uv.lock",
        "01_cat-engine/fixtures/demo_cat_config.v1.json",
        "01_cat-engine/fixtures/synthetic_item_bank.v1.json",
        "13_deployment/systemd/psynova-school-cat.service",
    }
    selected = [
        path
        for path in tracked
        if path in fixed
        or path.startswith("01_cat-engine/src/cat_engine/") and path.endswith(".py")
    ]
    required = fixed | {
        "01_cat-engine/src/cat_engine/api/app.py",
        "01_cat-engine/src/cat_engine/providers/adaptivetesting_provider.py",
    }
    if not required.issubset(selected):
        raise BundleError("required_source_missing")
    return sorted(selected)


def _bundle_name(source_path: str) -> str:
    if source_path.startswith("01_cat-engine/"):
        return "release/" + source_path.removeprefix("01_cat-engine/")
    if source_path == "13_deployment/systemd/psynova-school-cat.service":
        return "systemd/psynova-school-cat.service"
    raise BundleError("source_path_rejected")


def _canonical_fingerprint(files: dict[str, bytes]) -> str:
    source_names = sorted(
        name
        for name in files
        if name.startswith("release/src/cat_engine/") and name.endswith(".py")
    )
    source_names.append("release/pyproject.toml")
    digest = hashlib.sha256()
    for name in source_names:
        relative = ("01_cat-engine/" + name.removeprefix("release/")).encode("utf-8")
        data = files[name].replace(b"\r\n", b"\n")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def build_bundle(repo: Path, output: Path) -> dict[str, object]:
    repo = repo.resolve(strict=True)
    output = output.resolve()
    commit = _git(repo, "rev-parse", SOURCE_COMMIT).decode().strip()
    if commit != SOURCE_COMMIT:
        raise BundleError("source_commit_mismatch")

    payload: dict[str, bytes] = {}
    for source_path in _source_paths(repo):
        name = _bundle_name(source_path)
        if name in payload:
            raise BundleError("duplicate_bundle_path")
        payload[name] = _git(repo, "show", f"{SOURCE_COMMIT}:{source_path}")
    actual_hashes = {
        "source": _canonical_fingerprint(payload),
        "entrypoint": hashlib.sha256(payload["release/src/cat_engine/api/app.py"]).hexdigest(),
        "config": hashlib.sha256(payload["release/fixtures/demo_cat_config.v1.json"]).hexdigest(),
        "item_bank": hashlib.sha256(payload["release/fixtures/synthetic_item_bank.v1.json"]).hexdigest(),
    }
    if actual_hashes != {
        "source": CAT_SOURCE_SHA256,
        "entrypoint": CAT_ENTRYPOINT_SHA256,
        "config": CAT_CONFIG_SHA256,
        "item_bank": CAT_BANK_SHA256,
    }:
        raise BundleError("pinned_cat_fingerprint_mismatch")

    files = [
        {"path": name, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in sorted(payload.items())
    ]
    manifest = {
        "schema": "psynova.school-cat-bundle.v1",
        "source_commit": SOURCE_COMMIT,
        "python_version": PYTHON_VERSION,
        "synthetic_fixture_only": True,
        "psychological_interpretation_allowed": False,
        "cat_fingerprints": actual_hashes,
        "files": files,
    }
    payload["PAYLOAD_MANIFEST.json"] = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        output.open("xb") as raw_stream,
        gzip.GzipFile(
            filename="", mode="wb", fileobj=raw_stream, mtime=0, compresslevel=9
        ) as gzip_stream,
        tarfile.open(fileobj=gzip_stream, mode="w", format=tarfile.PAX_FORMAT) as archive,
    ):
        for name, data in sorted(payload.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))

    bundle_bytes = output.read_bytes()
    return {
        "bundle_path": str(output),
        "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "bundle_size_bytes": len(bundle_bytes),
        "file_count": len(files),
        "source_commit": SOURCE_COMMIT,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_bundle(args.repo_root, args.output)
    except (BundleError, OSError, UnicodeError):
        print(json.dumps({"status": "BLOCKED", "error_code": "bundle_build_failed"}))
        return 2
    print(json.dumps({"status": "PASS", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
