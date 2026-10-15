import json
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_prepare_dependencies as prepare


def _write_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".gitignore").write_text(
        "**/.venv/\n10_frontend/node_modules/\n10_frontend/dist/\n", encoding="utf-8"
    )
    (root / "README.md").write_text("synthetic tracked source\n", encoding="utf-8")
    root.joinpath("MODULES.md").write_text(
        "# modules\n\n| Module | Duty |\n|---|---|\n"
        + "".join(f"| {name} | test fixture |\n" for name in prepare.MODULES),
        encoding="utf-8",
    )
    for module in prepare.LOCK_FILES:
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
            expected_requires = prepare.PYTHON_REQUIRES.get(
                module, f">={minor[0]}.{minor[1]},<{minor[0]}.{minor[1] + 1}"
            )
            build_system = ""
            if module in prepare.BUILD_BACKENDS:
                backend, requirements = prepare.BUILD_BACKENDS[module]
                build_system = (
                    "[build-system]\n"
                    f"requires = {json.dumps(list(requirements))}\n"
                    f'build-backend = "{backend}"\n\n'
                )
            (directory / "pyproject.toml").write_text(
                build_system
                + f'[project]\nname = "fixture-{module}"\nrequires-python = "{expected_requires}"\n',
                encoding="utf-8",
            )
            (directory / "uv.lock").write_text(
                f"# synthetic lock for {module}\n", encoding="utf-8"
            )


def _git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "add",
            ".",
        ],
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


def _repositories(tmp_path: Path, mutate_source=None) -> tuple[Path, Path]:
    source = tmp_path / "source"
    _write_repo(source)
    if mutate_source:
        mutate_source(source)
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


def test_plan_is_read_only_and_reports_source_head_and_lock_digests(
    tmp_path, monkeypatch
):
    source, target = _repositories(tmp_path)
    untracked_source_note = source / "10_frontend" / "output" / "user-owned.txt"
    untracked_source_note.parent.mkdir()
    untracked_source_note.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(prepare, "_python_version", lambda path: (3, 14, 0))
    monkeypatch.setattr(
        prepare, "_check_python_requirement", lambda root, module, version: None
    )
    before = prepare._snapshot(source)
    report, status = prepare.execute(_args(source, target / "not-created", "plan"))

    assert status == 0
    assert report["source_head"] == before.head
    assert report["lock_sha256"] == before.lock_sha256
    assert all(stage["state"] == "planned" for stage in report["stages"])
    assert not (target / "not-created").exists()


def test_install_uses_only_offline_locked_commands_and_verifies_created_targets(
    tmp_path, monkeypatch
):
    source, target = _repositories(tmp_path)
    versions = {
        name: (*prepare.MODULES[name]["python_minor"], 0)
        for name in prepare.PYTHON_MODULES
    }
    monkeypatch.setattr(
        prepare, "_python_version", lambda path: versions["01_cat-engine"]
    )
    monkeypatch.setattr(
        prepare,
        "_check_python_requirement",
        lambda root, module, version: None,
    )
    monkeypatch.setattr(prepare, "_resolve_executable", lambda name: f"fake-{name}")
    monkeypatch.setattr(
        prepare, "_node_and_npm_cli", lambda: ("fake-node", "fake-npm-cli")
    )
    monkeypatch.setattr(
        prepare,
        "_public_import_check",
        lambda module, interpreter, root, *, protected_roots=(): None,
    )
    monkeypatch.setattr(
        prepare,
        "_frontend_check",
        lambda root, node, *, protected_roots=(): None,
    )
    commands = []
    frontend_configs = {}

    def fake_run_step(
        *,
        name,
        command,
        cwd,
        root,
        venv=None,
        extra_env=None,
        protected_roots=(),
        on_update=None,
    ):
        commands.append(command)
        if name == prepare.FRONTEND_MODULE:
            frontend_configs.update(extra_env or {})
        if on_update:
            assert on_update({"name": name, "state": "running", "exit_code": None})
        output = prepare._target_path(root, name)
        output.mkdir(parents=True)
        stage = {"name": name, "state": "succeeded", "exit_code": 0}
        if on_update:
            assert on_update(stage)
        return stage

    monkeypatch.setattr(prepare, "_run_step", fake_run_step)
    report, status = prepare.execute(_args(source, target))

    assert status == 0
    assert [stage["state"] for stage in report["stages"]] == ["succeeded"] * len(
        prepare.MODULES
    ) + ["succeeded"]
    assert all("--offline" in command for command in commands)
    assert all(
        "--frozen" in command
        and "--no-config" in command
        and "--no-python-downloads" in command
        for command in commands[: len(prepare.PYTHON_MODULES)]
    )
    assert all(
        "--no-dev" in command for command in commands[: len(prepare.PYTHON_MODULES)]
    )
    python_commands = {
        Path(command[command.index("--project") + 1]).name: command
        for command in commands[: len(prepare.PYTHON_MODULES)]
    }
    assert "--no-install-project" in python_commands["11_database"]
    for module in ("05_rag-engine", "08_safety-engine"):
        assert python_commands[module][-2:] == ["--extra", "runtime"]
    assert "--extra" not in python_commands["06_llm-runtime"]
    assert commands[-1][-3:] == ["ci", "--offline", "--ignore-scripts"]
    user_config = target / prepare.FRONTEND_MODULE / prepare.NPM_USER_CONFIG_FILENAME
    global_config = (
        target / prepare.FRONTEND_MODULE / prepare.NPM_GLOBAL_CONFIG_FILENAME
    )
    assert user_config.read_bytes() == global_config.read_bytes() == b""
    assert user_config != global_config
    assert Path(frontend_configs["NPM_CONFIG_USERCONFIG"]) == user_config
    assert Path(frontend_configs["NPM_CONFIG_GLOBALCONFIG"]) == global_config
    assert report["target_head"] == report["source_head"]
    assert report["stages"][-1]["name"] == "manifest_integrity"
    assert report["run_state"] == "completed"
    saved = json.loads((target / prepare.STATE_FILENAME).read_text(encoding="utf-8"))
    assert saved["run_state"] == "completed"
    assert saved["target_head"] == report["target_head"]


def test_target_head_mismatch_is_rejected(tmp_path, monkeypatch):
    source, target = _repositories(tmp_path)
    (target / "README.md").write_text("different commit\n", encoding="utf-8")
    subprocess.run(
        [
            "git",
            "-C",
            str(target),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-am",
            "different source",
        ],
        check=True,
    )
    monkeypatch.setattr(prepare, "_python_version", lambda path: (3, 14, 0))
    monkeypatch.setattr(
        prepare, "_check_python_requirement", lambda root, module, version: None
    )

    with pytest.raises(prepare.PreparationError, match="TargetHeadMismatch"):
        prepare.execute(_args(source, target))


@pytest.mark.parametrize(
    ("relative", "contents"),
    [
        (Path("10_frontend/untracked.txt"), "untracked"),
        (Path("10_frontend/dist/ignored.js"), "ignored"),
    ],
)
def test_untracked_and_ignored_target_files_are_rejected(
    tmp_path, monkeypatch, relative, contents
):
    source, target = _repositories(tmp_path)
    injected = target / relative
    injected.parent.mkdir(parents=True, exist_ok=True)
    injected.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(prepare, "_python_version", lambda path: (3, 14, 0))
    monkeypatch.setattr(
        prepare, "_check_python_requirement", lambda root, module, version: None
    )

    with pytest.raises(
        prepare.PreparationError, match="TargetHasUntrackedOrIgnoredFiles"
    ):
        prepare.execute(_args(source, target))


def test_target_root_git_reparse_point_is_rejected(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir()
    git_metadata = target / ".git"
    original_lstat = Path.lstat

    def fake_lstat(path):
        if path == git_metadata:
            return SimpleNamespace(
                st_mode=stat.S_IFLNK,
                st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
            )
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    monkeypatch.setattr(
        prepare.os, "walk", lambda *args, **kwargs: iter([(str(target), [".git"], [])])
    )

    with pytest.raises(prepare.PreparationError, match="ReparsePoint"):
        prepare._reject_target_tree_artifacts(target)


def test_tracked_target_source_change_is_rejected(tmp_path, monkeypatch):
    source, target = _repositories(tmp_path)
    (target / "README.md").write_text("modified tracked source\n", encoding="utf-8")
    monkeypatch.setattr(prepare, "_python_version", lambda path: (3, 14, 0))
    monkeypatch.setattr(
        prepare, "_check_python_requirement", lambda root, module, version: None
    )

    with pytest.raises(prepare.PreparationError, match="TrackedFilesDifferFromHead"):
        prepare.execute(_args(source, target))


def test_unknown_local_git_config_is_rejected_without_printing_its_value(
    tmp_path, monkeypatch
):
    source, target = _repositories(tmp_path)
    subprocess.run(
        [
            "git",
            "-C",
            str(target),
            "config",
            "--local",
            "core.fsmonitor",
            "synthetic-hook",
        ],
        check=True,
    )
    monkeypatch.setattr(prepare, "_python_version", lambda path: (3, 14, 0))
    monkeypatch.setattr(
        prepare, "_check_python_requirement", lambda root, module, version: None
    )

    with pytest.raises(prepare.PreparationError, match="UnknownGitConfig"):
        prepare.execute(_args(source, target))


def test_project_npm_config_is_rejected(tmp_path, monkeypatch):
    source = tmp_path / "source"
    _write_repo(source)
    (source / "10_frontend" / ".npmrc").write_text(
        "registry=https://invalid.example/", encoding="utf-8"
    )
    _git_repo(source)
    target = tmp_path / "target"
    subprocess.run(["git", "clone", "--quiet", str(source), str(target)], check=True)
    monkeypatch.setattr(prepare, "_python_version", lambda path: (3, 14, 0))
    monkeypatch.setattr(
        prepare, "_check_python_requirement", lambda root, module, version: None
    )

    with pytest.raises(
        prepare.PreparationError, match="UnsupportedPackageManagerConfig"
    ):
        prepare.execute(_args(source, target, "plan"))


def test_nonpublic_python_lock_source_is_rejected(tmp_path, monkeypatch):
    def mutate(source):
        (source / "01_cat-engine" / "uv.lock").write_text(
            'version = 1\n[[package]]\nname = "fixture"\nversion = "1.0"\n'
            'source = { registry = "https://private.example/simple" }\n',
            encoding="utf-8",
        )

    source, target = _repositories(tmp_path, mutate)
    monkeypatch.setattr(prepare, "_python_version", lambda path: (3, 14, 0))
    monkeypatch.setattr(
        prepare, "_check_python_requirement", lambda root, module, version: None
    )

    with pytest.raises(prepare.PreparationError, match="UnsupportedPythonLockSource"):
        prepare.execute(_args(source, target, "plan"))


def test_nonpublic_frontend_lock_source_is_rejected(tmp_path, monkeypatch):
    def mutate(source):
        path = source / "10_frontend" / "package-lock.json"
        lock = json.loads(path.read_text(encoding="utf-8"))
        lock["packages"]["node_modules/fixture"] = {
            "version": "1.0.0",
            "resolved": "https://private.example/fixture.tgz",
        }
        path.write_text(json.dumps(lock), encoding="utf-8")

    source, target = _repositories(tmp_path, mutate)
    monkeypatch.setattr(prepare, "_python_version", lambda path: (3, 14, 0))
    monkeypatch.setattr(
        prepare, "_check_python_requirement", lambda root, module, version: None
    )

    with pytest.raises(prepare.PreparationError, match="UnsupportedFrontendLockSource"):
        prepare.execute(_args(source, target, "plan"))


def test_unsupported_build_backend_is_rejected(tmp_path, monkeypatch):
    def mutate(source):
        path = source / "01_cat-engine" / "pyproject.toml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "setuptools.build_meta", "fixture.arbitrary_backend"
            ),
            encoding="utf-8",
        )

    source, target = _repositories(tmp_path, mutate)
    monkeypatch.setattr(prepare, "_python_version", lambda path: (3, 14, 0))
    monkeypatch.setattr(
        prepare, "_check_python_requirement", lambda root, module, version: None
    )

    with pytest.raises(prepare.PreparationError, match="UnsupportedBuildSystem"):
        prepare.execute(_args(source, target, "plan"))


def test_worktree_specific_git_config_is_checked(tmp_path):
    _, target = _repositories(tmp_path)
    config = Path(prepare._git(target, ["rev-parse", "--git-path", "config.worktree"]))
    if not config.is_absolute():
        config = target / config
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("[core]\nfsmonitor = synthetic-hook\n", encoding="utf-8")

    with pytest.raises(prepare.PreparationError, match="UnknownGitConfig"):
        prepare._git_config_is_allowed(target)


def test_source_tracked_change_is_rejected_but_untracked_source_is_allowed(
    tmp_path, monkeypatch
):
    source, target = _repositories(tmp_path)
    (source / "README.md").write_text("changed tracked source\n", encoding="utf-8")
    monkeypatch.setattr(prepare, "_python_version", lambda path: (3, 14, 0))
    monkeypatch.setattr(
        prepare, "_check_python_requirement", lambda root, module, version: None
    )

    with pytest.raises(prepare.PreparationError, match="TrackedFilesDifferFromHead"):
        prepare.execute(_args(source, target, "plan"))


def test_node_executable_is_paired_with_its_own_npm_cli(tmp_path, monkeypatch):
    node = tmp_path / "node.exe"
    node.write_bytes(b"synthetic exe marker")
    cli = tmp_path / "node_modules" / "npm" / "bin" / "npm-cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("synthetic cli marker", encoding="utf-8")
    monkeypatch.setattr(
        prepare,
        "_resolve_executable",
        lambda name: str(prepare._canonical(node, must_exist=True)),
    )

    assert prepare._node_and_npm_cli() == (
        str(node.resolve()).lower(),
        str(cli.resolve()).lower(),
    )


def test_executable_wrapper_is_rejected(tmp_path, monkeypatch):
    wrapper = tmp_path / "node.cmd"
    wrapper.write_text("synthetic wrapper", encoding="utf-8")
    monkeypatch.setattr(prepare, "_tool", lambda name: str(wrapper))

    with pytest.raises(prepare.PreparationError, match="UntrustedExecutableWrapper"):
        prepare._resolve_executable("node.exe")


def test_failed_install_persists_stage_and_stops_following_modules(
    tmp_path, monkeypatch
):
    source, target = _repositories(tmp_path)
    versions = {
        name: (*prepare.MODULES[name]["python_minor"], 0)
        for name in prepare.PYTHON_MODULES
    }
    monkeypatch.setattr(
        prepare, "_python_version", lambda path: versions["01_cat-engine"]
    )
    monkeypatch.setattr(
        prepare, "_check_python_requirement", lambda root, module, version: None
    )
    monkeypatch.setattr(prepare, "_resolve_executable", lambda name: f"fake-{name}")
    monkeypatch.setattr(
        prepare, "_node_and_npm_cli", lambda: ("fake-node", "fake-npm-cli")
    )
    called = []

    def fail_first_step(
        *,
        name,
        command,
        cwd,
        root,
        venv=None,
        extra_env=None,
        protected_roots=(),
        on_update=None,
    ):
        called.append(name)
        on_update({"name": name, "state": "running", "exit_code": None})
        failed = {
            "name": name,
            "state": "failed",
            "exit_code": 23,
            "error_class": "CommandFailed",
        }
        on_update(failed)
        return failed

    monkeypatch.setattr(prepare, "_run_step", fail_first_step)
    report, status = prepare.execute(_args(source, target))

    saved = json.loads((target / prepare.STATE_FILENAME).read_text(encoding="utf-8"))
    assert status == 1
    assert report["run_state"] == saved["run_state"] == "partial"
    assert saved["stages"][0]["error_class"] == "CommandFailed"
    assert [stage["state"] for stage in saved["stages"][1 : len(prepare.MODULES)]] == [
        "pending"
    ] * (len(prepare.MODULES) - 1)
    assert saved["stages"][-1]["name"] == "manifest_integrity"
    assert saved["stages"][-1]["state"] == "succeeded"
    assert called == ["01_cat-engine"]


@pytest.mark.parametrize(
    ("module", "declared"),
    [
        ("05_rag-engine", ">=3.10,<3.15"),
        ("06_llm-runtime", ">=3.11"),
    ],
)
def test_real_module_manifests_allow_exact_reviewed_range_on_pinned_python(
    module, declared
):
    root = Path(__file__).resolve().parents[2]
    with (root / module / "pyproject.toml").open("rb") as stream:
        project = prepare.tomllib.load(stream)

    assert project["project"]["requires-python"] == declared
    prepare._check_python_requirement(root, module, (3, 12, 13))


@pytest.mark.parametrize(
    ("module", "declared"),
    [
        ("05_rag-engine", ">=3.10,<3.15,!=3.12.0"),
        ("06_llm-runtime", ">=3.11,<4"),
    ],
)
def test_unreviewed_python_requirement_changes_are_rejected(tmp_path, module, declared):
    module_root = tmp_path / module
    module_root.mkdir()
    (module_root / "pyproject.toml").write_text(
        f'[project]\nname = "fixture"\nrequires-python = "{declared}"\n',
        encoding="utf-8",
    )

    with pytest.raises(prepare.PreparationError, match="PythonRequirementMismatch"):
        prepare._check_python_requirement(tmp_path, module, (3, 12, 13))


@pytest.mark.parametrize("module", ["05_rag-engine", "06_llm-runtime"])
def test_broader_manifest_does_not_broaden_selected_runtime(module):
    root = Path(__file__).resolve().parents[2]

    with pytest.raises(prepare.PreparationError, match="PythonVersionMismatch"):
        prepare._check_python_requirement(root, module, (3, 13, 0))


def test_target_venv_python_version_is_checked_after_sync(tmp_path, monkeypatch):
    _, target = _repositories(tmp_path)
    python = target / "01_cat-engine" / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"fake interpreter marker")

    def fake_subprocess_run(args, **kwargs):
        assert "text" not in kwargs
        return subprocess.CompletedProcess(args, 0, stdout=b"\xff", stderr=b"\xfe")

    monkeypatch.setattr(prepare.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(prepare, "_python_version", lambda path: (3, 12, 13))

    with pytest.raises(prepare.PreparationError, match="PythonVersionMismatch"):
        prepare._public_import_check("01_cat-engine", sys.executable, target)


def test_unexpected_runner_error_rewrites_persisted_state_to_partial(
    tmp_path, monkeypatch
):
    source, target = _repositories(tmp_path)
    report = {
        "schema_version": "school-dependency-preparation.v1",
        "mode": "install",
        "run_state": "running",
        "source_head": prepare._snapshot(source).head,
        "stages": [{"name": "01_cat-engine", "state": "running", "exit_code": None}],
    }
    state_path = target / prepare.STATE_FILENAME
    state_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(prepare, "ACTIVE_INSTALL_STATE_ROOT", target)

    recovered = prepare._mark_active_install_partial("UnexpectedError")
    saved = json.loads(state_path.read_text(encoding="utf-8"))

    assert recovered is not None
    assert recovered["run_state"] == saved["run_state"] == "partial"
    assert saved["stages"][-1] == {
        "name": "runner",
        "state": "failed",
        "exit_code": None,
        "error_class": "UnexpectedError",
    }


def test_existing_environment_is_rejected_before_any_install(tmp_path, monkeypatch):
    source, target = _repositories(tmp_path)
    (target / "01_cat-engine" / ".venv").mkdir()
    monkeypatch.setattr(prepare, "_python_version", lambda path: (3, 14, 0))
    monkeypatch.setattr(
        prepare, "_check_python_requirement", lambda root, module, version: None
    )
    called = False

    def unexpected_run(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("installer must not run")

    monkeypatch.setattr(prepare, "_run_step", unexpected_run)
    with pytest.raises(prepare.PreparationError, match="TargetEnvironmentExists"):
        prepare.execute(_args(source, target))
    assert not called


def test_npm_config_files_are_created_empty_and_distinct(tmp_path):
    _, target = _repositories(tmp_path)

    user_config, global_config = prepare._create_npm_config_files(target)

    assert user_config != global_config
    assert user_config.read_bytes() == b""
    assert global_config.read_bytes() == b""


def test_npm_config_collision_is_rejected_without_overwrite_or_partial_creation(
    tmp_path,
):
    _, target = _repositories(tmp_path)
    user_config = target / prepare.FRONTEND_MODULE / prepare.NPM_USER_CONFIG_FILENAME
    global_config = (
        target / prepare.FRONTEND_MODULE / prepare.NPM_GLOBAL_CONFIG_FILENAME
    )
    user_config.write_text("preserve-me", encoding="utf-8")

    with pytest.raises(prepare.PreparationError, match="NpmConfigArtifactExists"):
        prepare._create_npm_config_files(target)

    assert user_config.read_text(encoding="utf-8") == "preserve-me"
    assert not global_config.exists()


def test_npm_config_reparse_point_is_rejected_before_creation(tmp_path, monkeypatch):
    _, target = _repositories(tmp_path)
    user_config = target / prepare.FRONTEND_MODULE / prepare.NPM_USER_CONFIG_FILENAME
    global_config = (
        target / prepare.FRONTEND_MODULE / prepare.NPM_GLOBAL_CONFIG_FILENAME
    )
    original_reject = prepare._reject_reparse_path

    def reject_user_config(path, **kwargs):
        if path == user_config:
            raise prepare.PreparationError("ReparsePoint")
        return original_reject(path, **kwargs)

    monkeypatch.setattr(prepare, "_reject_reparse_path", reject_user_config)

    with pytest.raises(prepare.PreparationError, match="ReparsePoint"):
        prepare._create_npm_config_files(target)

    assert not user_config.exists()
    assert not global_config.exists()


def test_npm_config_creation_failure_keeps_already_created_file(tmp_path, monkeypatch):
    _, target = _repositories(tmp_path)
    user_config = target / prepare.FRONTEND_MODULE / prepare.NPM_USER_CONFIG_FILENAME
    global_config = (
        target / prepare.FRONTEND_MODULE / prepare.NPM_GLOBAL_CONFIG_FILENAME
    )
    original_open = Path.open

    def fail_global_config(path, *args, **kwargs):
        if path == global_config:
            raise OSError("synthetic create failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_global_config)

    with pytest.raises(
        prepare.PreparationError, match="NpmConfigArtifactCreationFailed"
    ):
        prepare._create_npm_config_files(target)

    assert user_config.exists()
    assert user_config.read_bytes() == b""
    assert not global_config.exists()


def test_clean_child_environment_drops_redirects_and_preserves_d_cache(
    monkeypatch, tmp_path
):
    source, _ = _repositories(tmp_path)
    target = source.parent / "install-target"
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
    monkeypatch.setenv("PIP_CACHE_DIR", str(source / "cache"))
    monkeypatch.setenv("USERNAME", "synthetic-current-user")

    env = prepare._child_environment(
        root=target,
        venv=target / ".venv",
        protected_roots=(source,),
    )

    assert all(name not in env for name in blocked)
    assert Path(env["UV_CACHE_DIR"]).resolve() == Path(r"D:\Dev\cache\uv").resolve()
    assert "PIP_CACHE_DIR" not in env
    assert env["UV_PROJECT_ENVIRONMENT"].endswith(".venv")
    assert env["USERNAME"] == "synthetic-current-user"

    monkeypatch.delenv("USERNAME")
    env_without_username = prepare._child_environment(root=target)
    assert "USERNAME" not in env_without_username


def test_run_step_never_includes_child_output_in_report(tmp_path, monkeypatch):
    def fake_subprocess_run(*args, **kwargs):
        assert "text" not in kwargs
        return subprocess.CompletedProcess(
            args[0],
            17,
            stdout=b"\xfftoken-like-private-output",
            stderr=b"\xfep rivate error",
        )

    monkeypatch.setattr(prepare.subprocess, "run", fake_subprocess_run)
    stage = prepare._run_step(
        name="fixture", command=["fake"], cwd=tmp_path, root=tmp_path
    )

    assert stage == {
        "name": "fixture",
        "state": "failed",
        "exit_code": 17,
        "error_class": "CommandFailed",
    }
    assert "private" not in json.dumps(stage)


def test_frontend_check_ignores_non_utf8_child_output(tmp_path, monkeypatch):
    def fake_subprocess_run(args, **kwargs):
        assert "text" not in kwargs
        return subprocess.CompletedProcess(args, 0, stdout=b"\xff", stderr=b"\xfe")

    monkeypatch.setattr(prepare.subprocess, "run", fake_subprocess_run)

    prepare._frontend_check(tmp_path, "node.exe")


@pytest.mark.parametrize(
    ("probe", "expected_error"),
    [
        (lambda: prepare._git(Path.cwd(), ["status"]), "GitInspectionFailed"),
        (
            lambda: prepare._python_version(Path(sys.executable)),
            "InterpreterProbeFailed",
        ),
    ],
)
def test_utf8_probe_decode_error_is_returned_as_fixed_preparation_error(
    monkeypatch, probe, expected_error
):
    def decode_failure(*args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(prepare.subprocess, "run", decode_failure)

    with pytest.raises(prepare.PreparationError, match=expected_error):
        probe()
