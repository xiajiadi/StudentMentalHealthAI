"""Install the PsyNova school preview into an isolated Windows user directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import webbrowser
import zipfile
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO.parent
WORKSPACE = ROOT / ".StudentMentalHealthAI-school-install-20261123-v2-preview"
DOWNLOADS = ROOT / "downloads"
RUNTIMES = ROOT / "runtime"
PORTS = {"database": 3344, "backend": 8088, "frontend": 4178, "standard-cat": 8180}
PYTHON_MODULES = {"11_database": "3.12.13", "09_backend": "3.12.13", "01_cat-engine": "3.14.6"}
DOWNLOAD_BASE = "https://registry.ollama.ai/v2/library/qwen2.5"
QWEN_MODEL = "7b-instruct-q4_K_M"
QWEN_MANIFEST_SHA = "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(argv: list[str | Path], *, cwd: Path = REPO, limit: int = 1800) -> None:
    subprocess.run([str(item) for item in argv], cwd=cwd, check=True, timeout=limit)


def fetch(url: str, digest: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and sha256(destination) == digest:
        return
    partial = destination.with_suffix(destination.suffix + ".download")
    curl = Path(os.environ["SystemRoot"]) / "System32" / "curl.exe"
    run([
        curl, "--fail", "--location", "--proto", "=https", "--proto-redir", "=https",
        "--retry", "2", "--connect-timeout", "15", "--output", partial, url,
    ], limit=7200)
    if sha256(partial) != digest:
        raise ValueError(f"Download checksum mismatch for {destination.name}")
    partial.replace(destination)


def portable(name: str, asset: dict[str, str]) -> Path:
    archive = DOWNLOADS / f"{name}.zip"
    fetch(asset["url"], asset["sha256"], archive)
    destination = RUNTIMES / name
    marker = destination / ".archive-sha256"
    if destination.exists():
        if marker.read_text("ascii") != asset["sha256"]:
            raise ValueError(f"Existing {name} runtime does not match the archive")
        return destination / asset.get("subdir", "")
    temporary = RUNTIMES / f"{name}.unpacking"
    temporary.mkdir(exist_ok=False)
    try:
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                path = PurePosixPath(item.filename)
                if (
                    path.is_absolute() or ".." in path.parts
                    or any(":" in part or "\\" in part for part in path.parts)
                    or stat.S_ISLNK(item.external_attr >> 16)
                ):
                    raise ValueError(f"Unsafe member in {name} runtime")
            bundle.extractall(temporary)
        (temporary / ".archive-sha256").write_text(asset["sha256"], encoding="ascii")
        temporary.rename(destination)
    finally:
        if temporary.is_dir():
            shutil.rmtree(temporary)
    return destination / asset.get("subdir", "")


def prepare_qwen(assets: dict[str, dict[str, str]]) -> dict[str, str]:
    program = portable("ollama-0.33.3", assets["ollama"])
    models = ROOT / "qwen-models"
    manifest = models / "manifests" / "registry.ollama.ai" / "library" / "qwen2.5" / QWEN_MODEL
    fetch(f"{DOWNLOAD_BASE}/manifests/{QWEN_MODEL}", QWEN_MANIFEST_SHA, manifest)
    model = json.loads(manifest.read_bytes())
    for entry in (model["config"], *model["layers"]):
        digest = entry["digest"].removeprefix("sha256:")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("Pinned Qwen manifest contains an invalid digest")
        blob = models / "blobs" / f"sha256-{digest}"
        fetch(f"{DOWNLOAD_BASE}/blobs/sha256:{digest}", digest, blob)
        if blob.stat().st_size != entry["size"]:
            raise ValueError("Pinned Qwen asset has an unexpected length")
    return {"ollama": str(program), "models": str(models), "model": f"qwen2.5:{QWEN_MODEL}"}


def install(uv: Path, *, qwen: bool, open_browser: bool) -> None:
    if os.name != "nt" or not uv.is_file():
        raise ValueError("Run the Windows x64 installer")
    assets = json.loads((Path(__file__).parent / "runtime-assets.json").read_text("utf-8"))
    RUNTIMES.mkdir(exist_ok=True)
    node = portable("node-24.15.0", assets["node"])
    powershell = portable("powershell-7.5.3", assets["powershell"])
    mysql = portable("mysql-8.4.8", assets["mysql"])
    # Only the installer and its child processes use the bundled executables.
    os.environ["PATH"] = os.pathsep.join((str(node), str(powershell), os.environ["PATH"]))
    os.environ["UV_PYTHON_INSTALL_DIR"] = str(ROOT / "python")
    os.environ["UV_CACHE_DIR"] = str(ROOT / "uv-cache")
    os.environ["npm_config_cache"] = str(ROOT / "npm-cache")
    os.environ["PYTHONUTF8"] = "1"
    os.environ.pop("PYTHONPATH", None)
    os.environ.pop("PYTHONHOME", None)
    for module, python in PYTHON_MODULES.items():
        target = REPO / module
        run([uv, "sync", "--locked", "--no-dev", "--managed-python", "--python", python], cwd=target)
    run([node / "node.exe", node / "node_modules/npm/bin/npm-cli.js", "ci", "--no-audit", "--no-fund"],
        cwd=REPO / "10_frontend")
    if qwen:
        paths = prepare_qwen(assets)
        (ROOT / "qwen-local-assets.json").write_text(json.dumps(paths, indent=2), encoding="utf-8")
    database_python = REPO / "11_database/.venv/Scripts/python.exe"
    command = [
        database_python, REPO / "13_deployment/psynova_launcher.py", "install",
        "--demo-profile", "school-empty", "--workspace", WORKSPACE,
        "--mysql-bin", mysql / "bin",
    ]
    for name, port in PORTS.items():
        command.extend((f"--{name}-port", str(port)))
    run(command)
    print("本机学校工作区已就绪。网址为 http://127.0.0.1:4178/login")
    print("初始管理员凭据仅由安装此软件的 Windows 用户读取")
    if open_browser:
        webbrowser.open("http://127.0.0.1:4178/login")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument("--prepare-qwen", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        install(args.uv, qwen=args.prepare_qwen, open_browser=not args.no_browser)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"安装中止：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
