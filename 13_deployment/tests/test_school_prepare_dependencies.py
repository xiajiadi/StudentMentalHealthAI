import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_prepare_dependencies as prepare


def _write_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    root.joinpath("MODULES.md").write_text(
        "# modules\n\n| Module | Duty |\n|---|---|\n"
        + "".join(f"| {name} | test fixture |\n" for name in prepare.MODULES),
        encoding="utf-8",
    )
    for module, files in prepare.LOCK_FILES.items():
        directory = root / module
        directory.mkdir(parents=True)
        if module == prepare.FRONTEND_MODULE:
            (directory / "package.json").write_text(
                json.dumps(
                    {
                        "name": "fixture-frontend",
                        "dependencies": {"vue": "3.5.42"},
                        "devDependencies": {"vite": "8.2.2", "typescript": "5.9.3"},
                    }
                ),
                encoding="utf-8",
            )
            (directory / "package-lock.json").write_text(
                json.dumps(
                    {
                        "name": "fixture-frontend",
                        "lockfileVersion": 3,
                        "packages": {
                            "": {},
                            "node_modules/vue": {"version": "3.5.42"},
                            "node_modules/vite": {"version": "8.2.2"},
                            "node_modules/typescript": {"version": "5.9.3"},
                        },
                    }
                ),
                encoding="utf-8",
            )
        else:
            minor = prepare.MODULES[module]["python_minor"]
            (directory / "pyproject.toml").write_text(
                f'[project]\nname = "fixture-{module}"\nrequires-python = ">={minor[0]}.{minor[1]},<{minor[0]}.{minor[1] + 1}"\n',
                encoding="utf-8",
            )
            (directory / "uv.lock").write_text(f"# synthetic lock for {module}\n", encoding="utf-8")


def _git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "add", "."],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        check=True,
    )


def _repositories(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    _write_repo(source)
    _git_repo(source)
    target = tmp_path / "target"
    subprocess.run(["git", "clone", "--quiet", str(source), str(target)], check=True)
    return source, target


def _args(source: Path, target: Path, mode: str = "install") -> SimpleNamespace:
    return SimpleNamespace(
        mode=mode,
        source_root=str(source),
        target_root=str(target),
        python=[f"{module}={sys.executable}" for module in prepare.PYTHON_MODULES],
    )


def test_plan_is_read_only_and_reports_source_head_and_lock_digests(tmp_path, monkeypatch):
    source, target = _repositories(tmp_path)
    monkeypatch.setattr(prepare, "_python_version", lambda path: (3, 14, 0))
    monkeypatch.setattr(prepare, "_check_python_requirement", lambda root, module, version: None)
    before = prepare._snapshot(source)
    report, status = prepare.execute(_args(source, target / "not-created", "plan"))

    assert status == 0
    assert report["source_head"] == before.head
    assert report["lock_sha256"] == before.lock_sha256
    assert all(stage["state"] == "planned" for stage in report["stages"])
    assert not (target / "not-created").exists()


def test_install_uses_only_offline_locked_commands_and_verifies_created_targets(tmp_path, monkeypatch):
    source, target = _repositories(tmp_path)
    versions = {name: (*prepare.MODULES[name]["python_minor"], 0) for name in prepare.PYTHON_MODULES}
    monkeypatch.setattr(prepare, "_python_version", lambda path: versions["01_cat-engine"])
    monkeypatch.setattr(
        prepare,
        "_check_python_requirement",
        lambda root, module, version: None,
    )
    monkeypatch.setattr(prepare, "_tool", lambda name: f"fake-{name}")
    monkeypatch.setattr(prepare, "_public_import_check", lambda module, interpreter, root: None)
    monkeypatch.setattr(prepare, "_frontend_check", lambda root, node: None)
    commands = []

    def fake_run_step(*, name, command, cwd, root, venv=None):
        commands.append(command)
        output = prepare._target_path(root, name)
        output.mkdir(parents=True)
        return {"name": name, "state": "succeeded", "exit_code": 0}

    monkeypatch.setattr(prepare, "_run_step", fake_run_step)
    report, status = prepare.execute(_args(source, target))

    assert status == 0
    assert [stage["state"] for stage in report["stages"]] == ["succeeded"] * 4 + ["succeeded"]
    assert all("--offline" in command for command in commands)
    assert all("--frozen" in command and "--no-python-downloads" in command for command in commands[:3])
    assert all("--no-dev" in command for command in commands[:3])
    assert "--no-install-project" in commands[2]
    assert commands[3][-3:] == ["ci", "--offline", "--ignore-scripts"]
    assert report["target_head"] == report["source_head"]
    assert report["stages"][-1]["name"] == "manifest_integrity"


def test_existing_environment_is_rejected_before_any_install(tmp_path, monkeypatch):
    source, target = _repositories(tmp_path)
    (target / "01_cat-engine" / ".venv").mkdir()
    monkeypatch.setattr(prepare, "_python_version", lambda path: (3, 14, 0))
    monkeypatch.setattr(prepare, "_check_python_requirement", lambda root, module, version: None)
    called = False

    def unexpected_run(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("installer must not run")

    monkeypatch.setattr(prepare, "_run_step", unexpected_run)
    with pytest.raises(prepare.PreparationError, match="TargetEnvironmentExists"):
        prepare.execute(_args(source, target))
    assert not called


def test_clean_child_environment_drops_redirects_and_preserves_d_cache(monkeypatch, tmp_path):
    source, _ = _repositories(tmp_path)
    blocked = (
        "DATABASE_URL",
        "SMHAI_HOME",
        "VITE_API_URL",
        "PYTHONPATH",
        "PYTHONHOME",
        "NODE_OPTIONS",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "UV_ACTIVE",
        "UV_PROJECT",
        "UV_CONFIG_FILE",
        "PIP_INDEX_URL",
        "UV_INDEX_URL",
        "NPM_CONFIG_REGISTRY",
    )
    for name in blocked:
        monkeypatch.setenv(name, "synthetic-value")
    monkeypatch.setenv("UV_CACHE_DIR", r"D:\Dev\cache\uv")

    env = prepare._child_environment(root=source, venv=source / "target" / ".venv")

    assert all(name not in env for name in blocked)
    assert Path(env["UV_CACHE_DIR"]).resolve() == Path(r"D:\Dev\cache\uv").resolve()
    assert env["UV_PROJECT_ENVIRONMENT"].endswith(".venv")


def test_run_step_never_includes_child_output_in_report(tmp_path, monkeypatch):
    def fake_subprocess_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 17, stdout="token-like-private-output", stderr="private error")

    monkeypatch.setattr(prepare.subprocess, "run", fake_subprocess_run)
    stage = prepare._run_step(name="fixture", command=["fake"], cwd=tmp_path, root=tmp_path)

    assert stage == {"name": "fixture", "state": "failed", "exit_code": 17, "error_class": "CommandFailed"}
    assert "private" not in json.dumps(stage)
