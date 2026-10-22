"""Build a deterministic, secret-free DeepSeek school runtime bundle."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

SOURCE_COMMIT = "83620b8fe3adf34fc252b17348861799d33bf1e4"
PYTHON_VERSION = "3.12.3"
MODEL_ID = "deepseek-flash"
API_BASE_URL = "https://api.deepseek.com"
SOURCE_FILES = (
    "06_llm-runtime/README.md",
    "06_llm-runtime/pyproject.toml",
    "06_llm-runtime/uv.lock",
    "06_llm-runtime/config/runtime.v1.json",
    "06_llm-runtime/config/models.deepseek.v1.json",
    "13_deployment/systemd/psynova-school-llm.service",
    "13_deployment/systemd/psynova-school-demo-llm.conf",
)


class BundleError(ValueError):
    """Raised when the fixed DeepSeek source cannot produce a safe bundle."""


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


def _bundle_name(path: str) -> str:
    if path.startswith("06_llm-runtime/"):
        return "release/" + path.removeprefix("06_llm-runtime/")
    if path.startswith("13_deployment/systemd/"):
        return "systemd/" + Path(path).name
    raise BundleError("source_path_rejected")


def _fingerprint(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name in sorted(files):
        relative = name.encode("utf-8")
        data = files[name].replace(b"\r\n", b"\n")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def build_bundle(repo: Path, output: Path) -> dict[str, object]:
    repo = repo.resolve(strict=True)
    commit = _git(repo, "rev-parse", SOURCE_COMMIT).decode("ascii").strip()
    if commit != SOURCE_COMMIT:
        raise BundleError("source_commit_mismatch")
    tracked = set(
        _git(repo, "ls-tree", "-r", "--name-only", SOURCE_COMMIT)
        .decode("utf-8", errors="strict")
        .splitlines()
    )
    sources = [
        *SOURCE_FILES,
        *sorted(
            path
            for path in tracked
            if path.startswith("06_llm-runtime/src/llm_runtime/")
            and path.endswith(".py")
        ),
    ]
    if not set(SOURCE_FILES).issubset(sources):
        raise BundleError("required_source_missing")
    payload: dict[str, bytes] = {}
    for source in sources:
        name = _bundle_name(source)
        if name in payload:
            raise BundleError("duplicate_bundle_path")
        payload[name] = _git(repo, "show", f"{SOURCE_COMMIT}:{source}")
    if not {
        "release/README.md",
        "release/pyproject.toml",
        "release/uv.lock",
        "release/config/runtime.v1.json",
        "release/config/models.deepseek.v1.json",
        "release/src/llm_runtime/api/app.py",
        "release/src/llm_runtime/cli.py",
        "release/src/llm_runtime/providers/deepseek.py",
        "systemd/psynova-school-llm.service",
        "systemd/psynova-school-demo-llm.conf",
    }.issubset(payload):
        raise BundleError("required_source_missing")
    model = json.loads(payload["release/config/models.deepseek.v1.json"])
    runtime = json.loads(payload["release/config/runtime.v1.json"])
    if (
        type(model) is not dict
        or model.get("cloud_fallback") is not False
        or type(model.get("models")) is not list
        or len(model["models"]) != 1
        or model["models"][0].get("provider_model_id") != MODEL_ID
        or model["models"][0].get("enabled") is not True
        or model["models"][0].get("fallback_eligible") is not False
    ):
        raise BundleError("model_registry_scope_mismatch")
    if type(runtime) is not dict or runtime.get("cloud_fallback") is not False:
        raise BundleError("runtime_config_scope_mismatch")
    unit = payload["systemd/psynova-school-llm.service"].decode("utf-8")
    if (
        "LoadCredentialEncrypted=deepseek-api-key:" not in unit
        or "LoadCredentialEncrypted=llm-runtime-auth.json:" not in unit
        or "SMHAI_LLM_PROVIDER=deepseek" not in unit
        or "IPAddressDeny=any" not in unit
        or "IPAddressAllow=127.0.0.1/32" not in unit
        or "IPAddressAllow=3.173.21.63/32" not in unit
        or "API_KEY=" in unit
        or "0.0.0.0/0" in unit
    ):
        raise BundleError("llm_unit_scope_mismatch")
    if b"API_KEY=" in payload["systemd/psynova-school-demo-llm.conf"]:
        raise BundleError("backend_dropin_scope_mismatch")

    file_records = [
        {"path": name, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in sorted(payload.items())
    ]
    manifest = {
        "schema": "psynova.school-deepseek-bundle.v1",
        "source_commit": SOURCE_COMMIT,
        "python_version": PYTHON_VERSION,
        "provider": "deepseek",
        "model_id": MODEL_ID,
        "api_base_url": API_BASE_URL,
        "synthetic_demo_only": True,
        "cloud_fallback": False,
        "files": file_records,
        "payload_fingerprint": _fingerprint(payload),
    }
    payload["PAYLOAD_MANIFEST.json"] = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        output.open("xb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as gz,
        tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as archive,
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
    bundle = output.read_bytes()
    return {
        "bundle_path": str(output),
        "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "bundle_size_bytes": len(bundle),
        "file_count": len(file_records),
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
    except (BundleError, OSError, UnicodeError, json.JSONDecodeError):
        print(json.dumps({"status": "BLOCKED", "error_code": "bundle_build_failed"}))
        return 2
    print(json.dumps({"status": "PASS", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
