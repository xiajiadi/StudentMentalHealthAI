from __future__ import annotations

import json

import pytest

from harness.controlled_product_eval import r1_source_manifest as source_manifest
from harness.controlled_product_eval.runner import RunnerError
from harness.controlled_product_eval.service_profiles import ServiceProfileError

_PARENT_COMMIT = "2b11d94242a296555cbb26ec6f6da77d747d3f0e"
_TEST_HEAD_COMMIT = "f" * 40
_FILE_BLOBS = {
    "09_backend/src/smhai_backend/core/config.py": "452c3be1efb12662b41f9c0a2e0b605cef560d23",
    "09_backend/tests/test_backend_round1.py": "2c28aaf9d0d6846856a44c965dfcbd3708ca8395",
}


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "d4-r1-remediation-source-manifest.v1",
        "baseline_commit": source_manifest.R1_PRODUCT_BASELINE_COMMIT,
        "parent_commit": _PARENT_COMMIT,
        "product_commit": source_manifest.R1_TIMEOUT_REMEDIATION_COMMIT,
        "files": [
            {"path": path, "git_blob_oid": blob}
            for path, blob in sorted(_FILE_BLOBS.items())
        ],
        "authorized_semantic_delta": dict(source_manifest._EXPECTED_SEMANTIC_DELTA),
    }


def _install_git_stub(
    monkeypatch: pytest.MonkeyPatch,
    manifest: dict[str, object],
    *,
    baseline_changes: list[str] | None = None,
    product_changes: list[str] | None = None,
    head_blob_overrides: dict[str, str] | None = None,
    fail_ancestor_for: str | None = None,
) -> None:
    baseline_changes = sorted(_FILE_BLOBS) if baseline_changes is None else baseline_changes
    product_changes = sorted(_FILE_BLOBS) if product_changes is None else product_changes
    head_blob_overrides = {} if head_blob_overrides is None else head_blob_overrides

    def fake_git(_repo_root, *arguments: str) -> str:
        if arguments[0] == "diff":
            left, right = arguments[3:5]
            paths = baseline_changes if left == source_manifest.R1_PRODUCT_BASELINE_COMMIT else product_changes
            return "\n".join(paths)
        if arguments[0] == "show":
            return json.dumps(manifest)
        if arguments[0] == "rev-parse":
            revision = arguments[1]
            if revision == f"{source_manifest.R1_TIMEOUT_REMEDIATION_COMMIT}^":
                return _PARENT_COMMIT
            if revision == f"{_TEST_HEAD_COMMIT}:{source_manifest.R1_REMEDIATION_SOURCE_MANIFEST_PATH}":
                return "a" * 40
            for path, blob in _FILE_BLOBS.items():
                if revision == f"{source_manifest.R1_TIMEOUT_REMEDIATION_COMMIT}:{path}":
                    return blob
                if revision == f"{_TEST_HEAD_COMMIT}:{path}":
                    return head_blob_overrides.get(path, blob)
        if arguments[0] == "merge-base":
            if fail_ancestor_for and arguments[-1] == fail_ancestor_for:
                raise ServiceProfileError("synthetic ancestry rejection")
            return ""
        raise AssertionError(f"unexpected git arguments: {arguments!r}")

    monkeypatch.setattr(source_manifest.service_profiles, "_git", fake_git)


def test_r1_source_manifest_binds_exact_committed_timeout_blobs(monkeypatch, tmp_path):
    _install_git_stub(monkeypatch, _manifest())

    binding = source_manifest.resolve_r1_product_source_binding(
        tmp_path,
        head_commit=_TEST_HEAD_COMMIT,
        dirty_paths=[],
    )

    assert binding["status"] == "PASS"
    assert binding["source_mode"] == "committed_r1_remediation_manifest"
    assert binding["product_source_commit"] == source_manifest.R1_TIMEOUT_REMEDIATION_COMMIT
    assert binding["product_parent_commit"] == _PARENT_COMMIT
    assert binding["manifest_blob_oid"] == "a" * 40
    assert binding["product_files"] == _manifest()["files"]
    assert binding["authorized_semantic_delta"] == source_manifest._EXPECTED_SEMANTIC_DELTA


def test_r1_source_manifest_rejects_any_dirty_worktree_path(monkeypatch, tmp_path):
    _install_git_stub(monkeypatch, _manifest())

    with pytest.raises(RunnerError, match="requires a clean worktree"):
        source_manifest.resolve_r1_product_source_binding(
            tmp_path,
            head_commit=_TEST_HEAD_COMMIT,
            dirty_paths=["12_evaluation/changed.py"],
        )


@pytest.mark.parametrize(
    "mutate,baseline_changes,product_changes,head_blob_overrides",
    [
        (lambda value: value.update(product_commit="f" * 40), None, None, None),
        (
            lambda value: value["files"][0].update(git_blob_oid="f" * 40),
            None,
            None,
            None,
        ),
        (
            lambda value: value["authorized_semantic_delta"].update(retry_policy_changed=True),
            None,
            None,
            None,
        ),
        (lambda _value: None, sorted([*_FILE_BLOBS, "09_backend/extra.py"]), None, None),
        (lambda _value: None, None, sorted([*_FILE_BLOBS, "09_backend/extra.py"]), None),
        (
            lambda _value: None,
            None,
            None,
            {"09_backend/src/smhai_backend/core/config.py": "f" * 40},
        ),
    ],
)
def test_r1_source_manifest_fails_closed_for_commit_hash_semantic_or_scope_drift(
    monkeypatch,
    tmp_path,
    mutate,
    baseline_changes,
    product_changes,
    head_blob_overrides,
):
    manifest = _manifest()
    mutate(manifest)
    _install_git_stub(
        monkeypatch,
        manifest,
        baseline_changes=baseline_changes,
        product_changes=product_changes,
        head_blob_overrides=head_blob_overrides,
    )

    with pytest.raises(RunnerError):
        source_manifest.resolve_r1_product_source_binding(
            tmp_path,
            head_commit=_TEST_HEAD_COMMIT,
            dirty_paths=[],
        )


def test_r1_source_manifest_rejects_unrelated_evaluation_head(monkeypatch, tmp_path):
    _install_git_stub(
        monkeypatch,
        _manifest(),
        fail_ancestor_for=_TEST_HEAD_COMMIT,
    )

    with pytest.raises(RunnerError):
        source_manifest.resolve_r1_product_source_binding(
            tmp_path,
            head_commit=_TEST_HEAD_COMMIT,
            dirty_paths=[],
        )


def test_r1_source_binding_keeps_original_baseline_when_product_sources_are_unchanged(
    monkeypatch,
    tmp_path,
):
    _install_git_stub(monkeypatch, _manifest(), baseline_changes=[])

    binding = source_manifest.resolve_r1_product_source_binding(
        tmp_path,
        head_commit=_TEST_HEAD_COMMIT,
        dirty_paths=[],
    )

    assert binding["source_mode"] == "accepted_r1_baseline"
    assert binding["product_source_commit"] == source_manifest.R1_PRODUCT_BASELINE_COMMIT
