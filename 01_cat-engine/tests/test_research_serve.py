from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import stat
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from cat_engine.domain.config import CATConfig
from cat_engine.research import http_app, serve
from cat_engine.research.http_app import WIRE_SCHEMA
from cat_engine.research.research_session import _config_sha256
from tests.research.test_research_http_app import _asgi_request


def _profile_document() -> dict[str, object]:
    thresholds = [-1.2, -0.3, 0.4, 1.0, 1.8]
    items = []
    for index in range(4):
        direction = "reverse" if index % 2 else "positive"
        items.append(
            {
                "item_id": f"TEST_ONLY_ITEM_{index + 1}",
                "qid": f"test_q_{index + 1}",
                "ipip100_code": "TEST_ONLY",
                "item_info_id": f"test_q_{index + 1}",
                "response_column": f"test_q_{index + 1}",
                "stem": f"Synthetic test statement {index + 1}.",
                "key_direction": direction,
                "response_transform": "identity" if direction == "positive" else "7 - response",
                "a": 0.9 + index * 0.1,
                "thresholds": [value + index * 0.03 for value in thresholds],
                "observed_n": 0,
                "source_locator": {
                    "url": "https://example.invalid/test-only",
                    "section": "synthetic unit fixture",
                    "key_block": f"{direction}_keyed",
                    "position_in_block": index + 1,
                    "crosswalk_file": "test-only-crosswalk.tsv",
                    "crosswalk_row": index + 1,
                    "item_info_file": "test-only-iteminfo.tab",
                },
                "fit_locator": {
                    "file": "test-only-fit.json",
                    "sha256": "a" * 64,
                    "parameter_key": f"test_q_{index + 1}",
                    "parameter_metric": "synthetic test fixture only",
                },
            }
        )
    return {
        "schema": "psynova.research-profile.v1",
        "profile_id": "serve-test-profile",
        "profile_type": "CAT_RESEARCH_PROFILE_CANDIDATE",
        "instrument_id": "TEST_ONLY_RESEARCH_INSTRUMENT",
        "dimension": "synthetic test dimension",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "psychological_interpretation_allowed": False,
        "response_scale": {
            "values": [1, 2, 3, 4, 5, 6],
            "category_labels": None,
            "category_labels_status": "test_only_labels_absent",
        },
        "scoring": {
            "parameter_orientation": "synthetic test keyed ordinal categories",
            "positive_key_transform": "identity",
            "reverse_key_transform": "7 - response",
            "transform_before_category_index_conversion": True,
            "no_person_scores_or_norms_included": True,
        },
        "model": {
            "package": "mirt",
            "version": "test-only",
            "itemtype": "graded",
            "factors": 1,
            "method": "test-only synthetic fixture",
            "latent_distribution": "Gaussian N(0,1)",
            "converged": True,
            "fit_sha256": "a" * 64,
            "calibration_sha256": "b" * 64,
        },
        "source": {"population": "Synthetic unit-test fixture only; no observations."},
        "rights": {
            "items": {"status": "test_only", "source_url": "https://example.invalid/test-only"},
            "dataset": {"license": "test-only; no data"},
            "profile": {"status": "research_only_candidate", "operational_release": False},
        },
        "provenance": {"created_at_utc": "test-only", "source_files": {}},
        "items": items,
        "not_approved_for": ["all operational and interpretive uses"],
    }


def _cat_config() -> CATConfig:
    return CATConfig.from_dict(
        {
            "config_version": "serve-test-config-v1",
            "model": "GRM",
            "estimator": "EAP",
            "selection_method": "MFI",
            "min_items": 4,
            "max_items": 4,
            "se_threshold": None,
            "initial_theta": 0.0,
            "prior_mean": 0.0,
            "prior_sd": 1.0,
            "optimization_interval": [-4.0, 4.0],
            "seed": 20261014,
            "exposure_control": "none",
            "content_balancing": "none",
        }
    )


def _write_config(root: Path) -> tuple[Path, str, dict[str, object]]:
    root.mkdir(parents=True, exist_ok=True)
    profile_doc = _profile_document()
    profile_raw = json.dumps(profile_doc, ensure_ascii=False, sort_keys=True).encode("utf-8")
    profile_path = root / "profile.json"
    profile_path.write_bytes(profile_raw)
    manifest_raw = b'{"synthetic_test_manifest":true}\n'
    manifest_path = root / "manifest.json"
    manifest_path.write_bytes(manifest_raw)
    profile_sha = hashlib.sha256(profile_raw).hexdigest()
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    config = _cat_config()
    binding = {
        "binding_ref": "serve-test-binding-01",
        "profile_ref": "serve-test-profile",
        "config_version": config.config_version,
        "config_sha256": _config_sha256(config),
        "cat_config": config.to_dict(),
    }
    doc: dict[str, object] = {
        "schema": serve.SERVICE_CONFIG_SCHEMA,
        "school_scope": {"school_id": 701, "scope": "school:701"},
        "resource_root": str(root),
        "listener": {"host": "127.0.0.1", "port": 48182},
        "signing": {
            "signing_version": "v2",
            "accepted_key_versions": ["v1", "v2"],
        },
        "profiles": [
            {
                "profile_ref": "serve-test-profile",
                "profile_schema": "psynova.research-profile.v1",
                "profile_path": str(profile_path),
                "profile_sha256": profile_sha,
                "manifest_path": str(manifest_path),
                "manifest_sha256": manifest_sha,
            }
        ],
        "bindings": [binding],
    }
    path = root / "service.json"
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest(), doc


def _handoff(config: serve.ResearchCATServiceConfig) -> bytes:
    token = b"derived-test-service-bearer-token-material-123456789"
    doc = {
        "schema": serve.SECRET_HANDOFF_SCHEMA,
        "bearer_token": token.decode("ascii"),
        "signing_version": config.signing_version,
        "keyring": {
            version: base64.urlsafe_b64encode(
                bytes.fromhex(("11" if version == "v1" else "22") * 32)
            ).decode("ascii").rstrip("=")
            for version in config.accepted_key_versions
        },
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"


def test_sha_pinned_config_builds_only_validated_bindings_and_compatible_app(tmp_path: Path) -> None:
    path, digest, _doc = _write_config(tmp_path / "research-service")
    config = serve.load_service_config(path, digest)
    bearer, authenticator = serve.read_secret_handoff(BytesIO(_handoff(config)), config)
    app = serve.build_research_http_app(
        config, service_bearer_token=bearer, authenticator=authenticator
    )

    assert config.school_scope == "school:701"
    assert config.host == "127.0.0.1"
    assert config.port == 48182
    assert set(app.state.research_bindings) == {"serve-test-binding-01"}
    assert app.state.research_bindings["serve-test-binding-01"].config_sha256 == config.bindings[0]["config_sha256"]
    assert repr(authenticator) == "VersionedHmacSnapshotAuthenticator(versions=<redacted>, keys=<redacted>)"

    endpoints = {
        route.path: route.endpoint for route in app.routes if hasattr(route, "endpoint")
    }
    health = endpoints["/health"]()
    assert health == {
        "status": "RESEARCH_ONLY",
        "research_only": True,
        "clinical_approval": False,
        "school_approval": False,
    }
    start_body = http_app._StartRequest.model_validate(
        {"schema": WIRE_SCHEMA, "binding_ref": "serve-test-binding-01"}
    )
    started = endpoints["/v1/sessions/start"](start_body)
    envelope = started["signed_snapshot"]
    assert envelope["signature"].startswith("rk1.v2.")
    resume_body = http_app._ResumeRequest.model_validate(
        {
            "schema": WIRE_SCHEMA,
            "binding_ref": "serve-test-binding-01",
            "session_ref": started["session_ref"],
            "signed_snapshot": envelope,
        }
    )
    resumed = endpoints["/v1/sessions/resume"](resume_body)
    assert resumed["signed_snapshot"]["signature"].startswith("rk1.v2.")


def test_ready_route_uses_asgi_request_injection_and_bearer_auth(tmp_path: Path) -> None:
    path, digest, _doc = _write_config(tmp_path / "asgi-ready")
    config = serve.load_service_config(path, digest)
    bearer, authenticator = serve.read_secret_handoff(BytesIO(_handoff(config)), config)
    app = serve.build_research_http_app(
        config, service_bearer_token=bearer, authenticator=authenticator
    )

    no_token_status, no_token = _asgi_request(
        app, "GET", "/_research/ready", token=None
    )
    wrong_token_status, wrong_token = _asgi_request(
        app, "GET", "/_research/ready", token=b"wrong-derived-token"
    )
    authorized_status, readiness = _asgi_request(
        app, "GET", "/_research/ready", token=bearer
    )
    assert no_token_status == 401
    assert no_token == {"error": {"code": "bearer_authentication_required"}}
    assert wrong_token_status == 401
    assert wrong_token == {"error": {"code": "bearer_authentication_required"}}
    assert authorized_status == 200
    assert set(readiness) == {
        "schema",
        "status",
        "research_only",
        "clinical_approval",
        "school_approval",
        "service_config_sha256",
        "registry_fingerprint",
        "binding_count",
        "school_scope",
    }
    assert readiness == {
        "schema": "psynova.research-service-ready.v1",
        "status": "READY",
        "research_only": True,
        "clinical_approval": False,
        "school_approval": False,
        "service_config_sha256": config.service_config_sha256,
        "registry_fingerprint": serve._loaded_registry_fingerprint(config),
        "binding_count": 1,
        "school_scope": "school:701",
    }
    assert re.fullmatch(r"[0-9a-f]{64}", readiness["registry_fingerprint"])


def test_authenticator_accepts_only_explicit_retained_rk1_versions() -> None:
    payload = b"synthetic snapshot bytes"
    keys = {"v1": b"\x11" * 32, "v2": b"\x22" * 32}
    auth = serve.VersionedHmacSnapshotAuthenticator(keys=keys, signing_version="v2")
    signature = auth.sign(payload)
    old_digest = hmac.new(keys["v1"], payload, hashlib.sha256).hexdigest()

    assert signature.startswith("rk1.v2.")
    assert auth.verify(payload, signature)
    assert auth.verify(payload, f"rk1.v1.{old_digest}")
    assert not auth.verify(payload, f"rk1.unretained.{old_digest}")
    assert not auth.verify(b"changed", signature)
    assert "22" * 32 not in repr(auth)


def test_config_hash_duplicate_json_and_closed_schema_fail_closed(tmp_path: Path) -> None:
    path, _digest, doc = _write_config(tmp_path / "config")
    with pytest.raises(serve.ResearchCATServeError, match="service_config_hash_mismatch"):
        serve.load_service_config(path, "0" * 64)

    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_bytes(b'{"schema":"a","schema":"b"}')
    with pytest.raises(serve.ResearchCATServeError, match="service_config_invalid"):
        serve.load_service_config(duplicate_path, hashlib.sha256(duplicate_path.read_bytes()).hexdigest())

    doc["unrecognized"] = True
    invalid_raw = json.dumps(doc, sort_keys=True).encode("utf-8")
    path.write_bytes(invalid_raw)
    with pytest.raises(serve.ResearchCATServeError, match="service_config_schema_invalid"):
        serve.load_service_config(path, hashlib.sha256(invalid_raw).hexdigest())


@pytest.mark.parametrize(
    ("mode", "attributes"),
    [(stat.S_IFLNK, 0), (stat.S_IFDIR, 0x400)],
)
def test_path_components_reject_symlink_and_windows_reparse_before_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: int,
    attributes: int,
) -> None:
    root = tmp_path / "resources"
    root.mkdir()
    target = root / "profile.json"
    target.write_text("synthetic", encoding="utf-8")
    actual_lstat = serve.os.lstat

    def lstat_with_reparse_component(path: object) -> object:
        if Path(path) == root:
            return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
        return actual_lstat(path)

    monkeypatch.setattr(serve.os, "lstat", lstat_with_reparse_component)
    with pytest.raises(serve.ResearchCATServeError, match="pinned_path_invalid"):
        serve._absolute_existing_path(str(target), "pinned_path_invalid")


@pytest.mark.parametrize(
    ("target_kind", "expected_code"),
    [
        ("config", "service_config_invalid"),
        ("resource_root", "resource_root_invalid"),
        ("profile", "pinned_path_invalid"),
        ("manifest", "pinned_path_invalid"),
    ],
)
def test_service_config_and_pinned_artifacts_reject_reparse_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_kind: str,
    expected_code: str,
) -> None:
    config_path, digest, doc = _write_config(tmp_path / target_kind)
    if target_kind == "config":
        blocked_component = config_path
    elif target_kind == "resource_root":
        blocked_component = Path(doc["resource_root"])
        config_path = config_path.parent.parent / "service-outside-resource.json"
        config_path.write_bytes((Path(doc["resource_root"]) / "service.json").read_bytes())
    elif target_kind == "profile":
        blocked_component = Path(doc["profiles"][0]["profile_path"])
    else:
        blocked_component = Path(doc["profiles"][0]["manifest_path"])
    actual_lstat = serve.os.lstat

    def lstat_with_reparse_component(path: object) -> object:
        if Path(path) == blocked_component:
            return SimpleNamespace(
                st_mode=stat.S_IFLNK,
                st_file_attributes=0x400,
            )
        return actual_lstat(path)

    monkeypatch.setattr(serve.os, "lstat", lstat_with_reparse_component)
    with pytest.raises(serve.ResearchCATServeError, match=expected_code):
        serve.load_service_config(config_path, digest)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("external_host", "loopback_listener_invalid"),
        ("bool_port", "loopback_listener_invalid"),
        ("binding_hash", "cat_config_hash_mismatch"),
        ("binding_config_extra", "binding_config_invalid"),
        ("duplicate_binding", "binding_config_invalid"),
        ("bad_signing_versions", "signing_config_invalid"),
    ],
)
def test_service_document_rejects_bad_bindings_and_listener_configuration(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    path, _digest, doc = _write_config(tmp_path / mutation)
    if mutation == "external_host":
        doc["listener"]["host"] = "0.0.0.0"  # type: ignore[index]
    elif mutation == "bool_port":
        doc["listener"]["port"] = True  # type: ignore[index]
    elif mutation == "binding_hash":
        doc["bindings"][0]["config_sha256"] = "c" * 64  # type: ignore[index]
    elif mutation == "binding_config_extra":
        doc["bindings"][0]["cat_config"]["extra"] = "x"  # type: ignore[index]
    elif mutation == "duplicate_binding":
        doc["bindings"].append(dict(doc["bindings"][0]))  # type: ignore[union-attr,index]
    elif mutation == "bad_signing_versions":
        doc["signing"]["accepted_key_versions"] = ["v1", "v1"]  # type: ignore[index]
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(raw)
    with pytest.raises(serve.ResearchCATServeError, match=expected):
        serve.load_service_config(path, hashlib.sha256(raw).hexdigest())


def test_secret_handoff_is_bounded_closed_and_requires_every_accepted_derived_key(
    tmp_path: Path,
) -> None:
    path, digest, _doc = _write_config(tmp_path / "secret-test")
    config = serve.load_service_config(path, digest)
    valid = json.loads(_handoff(config))

    for mutation in (
        "extra", "missing_version", "master_key_field", "short_bearer", "wrong_signing"
    ):
        altered = dict(valid)
        if mutation == "extra":
            altered["secret"] = "unexpected"
        elif mutation == "missing_version":
            altered["keyring"] = {
                "v2": base64.urlsafe_b64encode(
                    bytes.fromhex("22" * 32)
                ).decode().rstrip("=")
            }
        elif mutation == "master_key_field":
            altered["database_master_key"] = "00" * 32
        elif mutation == "short_bearer":
            altered["bearer_token"] = "short"
        elif mutation == "wrong_signing":
            altered["signing_version"] = "v1"
        raw = json.dumps(altered, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
        with pytest.raises(serve.ResearchCATServeError, match="secret_handoff_invalid"):
            serve.read_secret_handoff(BytesIO(raw), config)

    oversized = b"x" * (serve.MAX_SECRET_HANDOFF_BYTES + 1) + b"\n"
    with pytest.raises(serve.ResearchCATServeError, match="secret_handoff_invalid"):
        serve.read_secret_handoff(BytesIO(oversized), config)


def test_stop_pipe_sentinel_or_eof_requests_only_owned_server_shutdown() -> None:
    server = SimpleNamespace(should_exit=False)
    serve._watch_stop_pipe(BytesIO(serve.STOP_SENTINEL), server)
    assert server.should_exit is True

    server = SimpleNamespace(should_exit=False)
    serve._watch_stop_pipe(BytesIO(b""), server)
    assert server.should_exit is True


def test_uvicorn_configuration_disables_workers_reload_and_access_logs() -> None:
    cfg = serve._uvicorn_config(object(), host="127.0.0.1", port=48182)
    assert cfg.workers == 1
    assert cfg.reload is False
    assert cfg.access_log is False
    assert cfg.log_config is None
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 48182
