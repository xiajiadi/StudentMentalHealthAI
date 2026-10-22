"""Build a deterministic, secret-free bundle for the pinned ECS Safety sidecar."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

SOURCE_COMMIT = "798e3293ce6f21cf793b02e8dfb99ba53c6ad98e"
MODEL_REVISION = "fada3b2f655b89601929198343c94cd2f64d93cc"
MODEL_WEIGHT_SHA256 = "4f3ce47ebd968cddb67de08d8764f8ede7c410a7d1fb9e08145a4c7a2f2e5c0f"
OPA_VERSION = "1.20.2"
OPA_SHA256 = "69da5179ee403d10fa11bab6cfb4ffb0d23dba5f9b682fa977db772a1da5670f"


class BundleError(ValueError):
    """Raised when a pinned source commit cannot produce a safe bundle."""


def _run_git(repo: Path, *args: str) -> bytes:
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
    tracked = _run_git(repo, "ls-tree", "-r", "--name-only", SOURCE_COMMIT).decode(
        "utf-8", errors="strict"
    ).splitlines()
    selected: list[str] = []
    fixed = {
        "08_safety-engine/README.md",
        "08_safety-engine/THIRD_PARTY_NOTICES.md",
        "08_safety-engine/pyproject.toml",
        "08_safety-engine/uv.lock",
        "08_safety-engine/config/safety.v1.json",
        "08_safety-engine/config/rules.v1.json",
        "08_safety-engine/config/nemo/config.yml",
        "13_deployment/systemd/psynova-school-safety.service",
    }
    for path in tracked:
        if (
            path in fixed
            or path.startswith("08_safety-engine/src/safety_engine/")
            and path.endswith((".py", ".json", ".txt"))
            or path.startswith("08_safety-engine/policies/")
            and path.endswith(".rego")
            or path.startswith("08_safety-engine/templates/crisis/")
            and path.endswith(".json")
        ):
            selected.append(path)
    required = fixed | {
        "08_safety-engine/src/safety_engine/api/app.py",
        "08_safety-engine/src/safety_engine/api/factory.py",
        "08_safety-engine/src/safety_engine/service/engine.py",
        "08_safety-engine/policies/base.rego",
        "08_safety-engine/templates/crisis/crisis_system_zh-CN.json",
    }
    if not required.issubset(selected):
        raise BundleError("required_source_missing")
    return sorted(selected)


def _entry_name(source_path: str) -> str:
    if source_path.startswith("08_safety-engine/"):
        return "release/" + source_path.removeprefix("08_safety-engine/")
    if source_path.startswith("13_deployment/"):
        return "systemd/" + source_path.removeprefix("13_deployment/systemd/")
    raise BundleError("source_path_rejected")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_bundle(repo: Path, output: Path) -> dict[str, object]:
    repo = repo.resolve(strict=True)
    output = output.resolve()
    commit = _run_git(repo, "rev-parse", SOURCE_COMMIT).decode().strip()
    if commit != SOURCE_COMMIT:
        raise BundleError("source_commit_mismatch")

    payload: dict[str, bytes] = {}
    for source_path in _source_paths(repo):
        name = _entry_name(source_path)
        if name in payload:
            raise BundleError("duplicate_bundle_path")
        payload[name] = _run_git(repo, "show", f"{SOURCE_COMMIT}:{source_path}")

    files = [
        {"path": name, "size_bytes": len(data), "sha256": _sha256(data)}
        for name, data in sorted(payload.items())
    ]
    manifest = {
        "schema": "psynova.school-safety-bundle.v1",
        "source_commit": SOURCE_COMMIT,
        "model": {
            "repository": "Qwen/Qwen3Guard-Gen-0.6B",
            "revision": MODEL_REVISION,
            "weight_sha256": MODEL_WEIGHT_SHA256,
        },
        "opa": {"version": OPA_VERSION, "binary_sha256": OPA_SHA256},
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
        "bundle_sha256": _sha256(bundle_bytes),
        "bundle_size_bytes": len(bundle_bytes),
        "file_count": len(files),
        "source_commit": SOURCE_COMMIT,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = build_bundle(args.repo_root, args.output)
    except (BundleError, OSError, UnicodeError):
        print(json.dumps({"status": "BLOCKED", "error_code": "bundle_build_failed"}))
        return 2
    print(json.dumps({"status": "PASS", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
