from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from smhai_backend.domains.school_research import lifecycle
from smhai_backend.domains.school_research.probes import (
    ResearchCATReadinessProbe,
    WindowsListenerOwnerProbe,
)


class _Persistence:
    def __init__(self, key_provider: object | None = None) -> None:
        self._started = False
        self.identity_profile = "school_tenant"
        self.protection_reads = 0
        self._key_provider = key_provider or object()

    @property
    def protection(self) -> SimpleNamespace:
        self.protection_reads += 1
        return SimpleNamespace(key_provider=self._key_provider)


def _service_config(path: Path, *, port: int = 48182) -> tuple[Path, str]:
    resource_root = path.parent / "resources"
    resource_root.mkdir(exist_ok=True)
    document = {
        "schema": "psynova.research-cat-service.v1",
        "school_scope": {"school_id": 71, "scope": "school:71"},
        "resource_root": str(resource_root),
        "listener": {"host": "127.0.0.1", "port": port},
        "signing": {"signing_version": "v1", "accepted_key_versions": ["v1"]},
        "profiles": [],
        "bindings": [],
    }
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def _settings(tmp_path: Path, *, enabled: bool = True) -> SimpleNamespace:
    runtime_file = tmp_path / "runtime.json"
    runtime_file.write_text("{}", encoding="utf-8")
    service_file, service_sha = _service_config(tmp_path / "service.json")
    cat_source = tmp_path / "cat-source"
    (cat_source / "cat_engine" / "research").mkdir(parents=True)
    (cat_source / "cat_engine" / "research" / "serve.py").write_text(
        "# test fixture\n", encoding="utf-8"
    )
    dependencies = tmp_path / "cat-dependencies"
    dependencies.mkdir()
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"synthetic python executable")
    return SimpleNamespace(
        school_research_managed_enabled=enabled,
        school_research_enabled=True,
        environment="test",
        identity_profile="school_tenant",
        persistence_mode="mysql",
        school_research_runtime_file=str(runtime_file),
        school_research_runtime_sha256="a" * 64,
        school_research_service_file=str(service_file),
        school_research_service_sha256=service_sha,
        school_research_base_url="http://127.0.0.1:48182",
        school_research_cat_python=str(executable),
        school_research_cat_source=str(cat_source),
        school_research_cat_dependencies=str(dependencies),
    )


def test_managed_process_factory_is_inert_by_default() -> None:
    assert (
        lifecycle.build_school_research_process_factory(
            SimpleNamespace(school_research_managed_enabled=False), None
        )
        is None
    )
    assert lifecycle.build_school_research_process_factory(SimpleNamespace(), None) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("school_research_enabled", False),
        ("environment", "production"),
        ("identity_profile", "legacy_demo"),
        ("persistence_mode", "memory"),
    ],
)
def test_managed_process_factory_rejects_wrong_school_runtime(
    tmp_path: Path, field: str, value: object
) -> None:
    settings = _settings(tmp_path)
    setattr(settings, field, value)
    with pytest.raises(lifecycle.ResearchCATLifecycleError, match="managed_research_scope_invalid"):
        lifecycle.build_school_research_process_factory(settings, _Persistence())


def test_factory_is_lazy_requires_started_persistence_and_checks_service_url(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    settings.school_research_base_url = "http://127.0.0.1:48183"
    persistence = _Persistence()
    factory = lifecycle.build_school_research_process_factory(settings, persistence)
    assert callable(factory)
    assert persistence.protection_reads == 0

    with pytest.raises(lifecycle.ResearchCATLifecycleError, match="persistence_not_started"):
        factory()
    assert persistence.protection_reads == 0

    persistence._started = True
    with pytest.raises(lifecycle.ResearchCATLifecycleError, match="base_url_service_mismatch"):
        factory()
    assert persistence.protection_reads == 0


def test_factory_builds_manager_only_when_invoked_after_persistence_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    provider = object()
    persistence = _Persistence(provider)
    seen: dict[str, Any] = {}
    manager = object()

    def build(**kwargs: Any) -> object:
        seen.update(kwargs)
        return manager

    monkeypatch.setattr(lifecycle, "build_managed_research_process", build)
    factory = lifecycle.build_school_research_process_factory(settings, persistence)
    assert persistence.protection_reads == 0

    persistence._started = True
    assert factory() is manager
    assert persistence.protection_reads == 1
    assert seen["retained_key_provider"] is provider
    assert seen["expected_service_config_sha256"] == settings.school_research_service_sha256
    assert seen["base_executable"] == Path(settings.school_research_cat_python)
    assert isinstance(seen["readiness_probe"], ResearchCATReadinessProbe)
    assert isinstance(seen["listener_owner_probe"], WindowsListenerOwnerProbe)
    assert (
        seen["listener_owner_probe"].expected_executable
        == Path(settings.school_research_cat_python).resolve()
    )
    assert callable(seen["base_executable_probe"])
    with pytest.raises(lifecycle.ResearchCATLifecycleError, match="manager_factory_already_used"):
        factory()


@pytest.mark.parametrize(
    "report_mutation",
    [
        "wrong_version",
        "wrong_executable",
        "site_packages_outside_dependencies",
        "numpy_outside_dependencies",
        "site_not_disabled",
    ],
)
def test_readonly_base_python_probe_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_mutation: str,
) -> None:
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"synthetic executable")
    source = tmp_path / "cat-source"
    source.mkdir()
    dependencies = tmp_path / "cat-dependencies"
    dependencies.mkdir()
    outside_site = tmp_path / "Python314" / "Lib" / "site-packages"
    outside_site.mkdir(parents=True)
    numpy = dependencies / "numpy" / "__init__.py"
    fastapi = dependencies / "fastapi" / "__init__.py"
    numpy.parent.mkdir()
    fastapi.parent.mkdir()

    report: dict[str, object] = {
        "executable": os.path.normcase(os.path.realpath(executable)),
        "version": [3, 14],
        "no_site": True,
        "paths": [str(source), str(dependencies), str(tmp_path / "Python314" / "Lib")],
        "numpy_origin": str(numpy),
        "fastapi_origin": str(fastapi),
        "origins_from_dependency": True,
        "expected_executable_matches": True,
    }
    if report_mutation == "wrong_version":
        report["version"] = [3, 12]
    elif report_mutation == "wrong_executable":
        report["executable"] = str(tmp_path / "other-python.exe")
        report["expected_executable_matches"] = False
    elif report_mutation == "site_packages_outside_dependencies":
        report["paths"] = [*report["paths"], str(outside_site)]
    elif report_mutation == "numpy_outside_dependencies":
        report["numpy_origin"] = str(outside_site / "numpy.py")
    elif report_mutation == "site_not_disabled":
        report["no_site"] = False

    completed = SimpleNamespace(returncode=0, stdout=json.dumps(report).encode("utf-8"))
    commands: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> object:
        commands.append((command, kwargs))
        return completed

    monkeypatch.setattr(lifecycle.subprocess, "run", fake_run)
    assert not lifecycle._probe_cat_base_executable(
        executable, cat_source=source, cat_dependencies=dependencies
    )
    assert commands[0][0][1:3] == ["-S", "-P"]
    environment = commands[0][1]["env"]
    assert "PATH" not in environment
    assert "DATABASE_URL" not in environment
    assert environment["PYTHONPATH"] == os.pathsep.join((str(source), str(dependencies)))


def test_readonly_base_python_probe_accepts_exact_isolated_python314(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compile(lifecycle._BASE_PROBE_CODE, "<research-cat-base-probe>", "exec")
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"synthetic executable")
    source = tmp_path / "cat-source"
    source.mkdir()
    dependencies = tmp_path / "cat-dependencies"
    dependencies.mkdir()
    numpy = dependencies / "numpy" / "__init__.py"
    fastapi = dependencies / "fastapi" / "__init__.py"
    numpy.parent.mkdir()
    fastapi.parent.mkdir()
    report: dict[str, object] = {
        "executable": os.path.normcase(os.path.realpath(executable)),
        "version": [3, 14],
        "no_site": True,
        "paths": [str(source), str(dependencies), str(tmp_path / "Python314" / "Lib")],
        "numpy_origin": str(numpy),
        "fastapi_origin": str(fastapi),
        "origins_from_dependency": True,
        "expected_executable_matches": True,
    }
    monkeypatch.setattr(
        lifecycle.subprocess,
        "run",
        lambda _command, **_kwargs: SimpleNamespace(
            returncode=0, stdout=json.dumps(report).encode("utf-8")
        ),
    )
    assert lifecycle._probe_cat_base_executable(
        executable, cat_source=source, cat_dependencies=dependencies
    )


def test_pinned_service_config_parser_rejects_hash_duplicate_and_bad_listener(
    tmp_path: Path,
) -> None:
    service_file, digest = _service_config(tmp_path / "service.json")
    assert lifecycle._read_pinned_service_port(service_file, digest) == 48182
    with pytest.raises(lifecycle.ResearchCATLifecycleError, match="service_config_hash_mismatch"):
        lifecycle._read_pinned_service_port(service_file, "0" * 64)

    service_file.write_bytes(b'{"schema":"one","schema":"two"}')
    with pytest.raises(lifecycle.ResearchCATLifecycleError, match="service_config_invalid"):
        lifecycle._read_pinned_service_port(
            service_file, hashlib.sha256(service_file.read_bytes()).hexdigest()
        )
