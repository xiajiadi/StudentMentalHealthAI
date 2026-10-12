import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from school_restore_browser_qa import validate_restore_profile


def profile():
    return (
        {"phase": "DATA_KEYS_RUNTIME_VERIFIED_REQUIRES_BROWSER",
         "workspace_id": "target", "source_workspace_id": "source"},
        {"workspace_id": "source"}, {"workspace_id": "target", "port": 3309},
    )


def test_verified_restored_profile_is_accepted_without_native_calls():
    validate_restore_profile(*profile())


@pytest.mark.parametrize("case", ["phase", "source", "target", "port", "overlap", "missing"])
def test_wrong_restore_evidence_refused_before_credential_or_browser_io(case):
    state, source, target = profile()
    if case == "phase":
        state["phase"] = "FAILED_PRESERVED"
    elif case == "source":
        state["source_workspace_id"] = "other"
    elif case == "target":
        state["workspace_id"] = "other"
    elif case == "port":
        target["port"] = 3308
    elif case == "overlap":
        source["workspace_id"] = target["workspace_id"]
        state["source_workspace_id"] = source["workspace_id"]
    elif case == "missing":
        source.clear()
        state.pop("source_workspace_id")
    with pytest.raises(ValueError, match="Verified isolated"):
        validate_restore_profile(state, source, target)
