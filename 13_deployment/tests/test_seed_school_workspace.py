import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import seed_school_workspace as seed


def test_new_credentials_use_exclusive_sealed_storage(tmp_path, monkeypatch):
    saved = {}

    def write(path, values, *, exclusive):
        assert exclusive is True
        saved.update(values)
        path.write_bytes(b"sealed-test-container")

    monkeypatch.setattr(seed, "write_private", write)
    monkeypatch.setattr(seed, "read_private", lambda path: saved)
    slots = ("alpha.student", "beta.teacher")
    values = seed.credentials_for(tmp_path, slots)
    assert set(values) == set(slots)
    assert all(pair[0].startswith("SYNTHETIC_") and len(pair[0]) <= 128 and 16 <= len(pair[1]) <= 256 for pair in values.values())
    assert saved["recipe_version"] == "school-contexts-v1"


def test_existing_credentials_not_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "school-accounts.private.dpapi"
    path.write_bytes(b"preserved")
    payload = {"recipe_version":"school-contexts-v1", "credentials":{}}
    monkeypatch.setattr(seed, "write_private", lambda *args,**kwargs: pytest.fail("must not rewrite"))
    monkeypatch.setattr(seed, "read_private", lambda path: payload)
    assert seed.credentials_for(tmp_path, ()) == {}
    assert path.read_bytes() == b"preserved"


def test_concurrent_creator_wins_without_overwrite(tmp_path, monkeypatch):
    payload = {"recipe_version":"school-contexts-v1", "credentials":{}}

    def write(*args,**kwargs):
        raise FileExistsError

    monkeypatch.setattr(seed, "write_private", write)
    monkeypatch.setattr(seed, "read_private", lambda path: payload)
    assert seed.credentials_for(tmp_path, ()) == {}


@pytest.mark.parametrize("payload", [{"recipe_version":"unknown","credentials":{}}, {"recipe_version":"school-contexts-v1","credentials":[]}])
def test_wrong_recipe_or_shape_rejected(tmp_path, monkeypatch, payload):
    (tmp_path / "school-accounts.private.dpapi").write_bytes(b"preserved")
    monkeypatch.setattr(seed, "read_private", lambda path: payload)
    with pytest.raises(ValueError):
        seed.credentials_for(tmp_path, ())
