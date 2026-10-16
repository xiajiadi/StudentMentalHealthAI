import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from school_account_handoff import (
    AccountHandoffError,
    _backend_preflight,
    _verify_private_acl,
    load_demo_accounts,
)

WORKSPACE_ID = "0123456789abcdef0123456789abcdef"
SLOTS = (
    "alpha.student",
    "alpha.teacher",
    "alpha.psychological_specialist",
    "alpha.admin",
)


def _preflight_result() -> dict:
    return {
        "database": "smhai_school_demo",
        "port": 3342,
        "workspace_id": WORKSPACE_ID,
        "data_directory": "synthetic-fixture-only",
        "identity_profile": "school_tenant",
        "schema_revision": "20261016_0024",
        "purpose": "application",
        "scope": "APPLICATION_CURRENT_REVISION",
        "preflight": "PASS",
        "module_clients": "HTTP",
    }


def test_backend_preflight_uses_closed_safe_output_and_strips_secret_environment(
    tmp_path, monkeypatch
):
    pythonw = tmp_path / "pythonw.exe"
    python = tmp_path / "python.exe"
    pythonw.touch()
    python.touch()
    monkeypatch.setattr(sys, "executable", str(pythonw))
    monkeypatch.setenv("DB_PASSWORD", "never-forward-this")
    monkeypatch.setenv("USERNAME", "synthetic-local-operator")
    captured = {}

    def run(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(_preflight_result()),
            stderr="",
        )

    monkeypatch.setattr("school_account_handoff.subprocess.run", run)
    _backend_preflight(
        tmp_path,
        {"workspace_id": WORKSPACE_ID, "database": "smhai_school_demo", "port": 3342},
    )

    assert captured["argv"][0] == str(python)
    assert captured["argv"][-1] == "--preflight-only"
    assert "DB_PASSWORD" not in captured["env"]
    assert captured["env"]["USERNAME"] == "synthetic-local-operator"


def test_backend_preflight_rejects_extra_output_fields_and_hides_child_output(
    tmp_path, monkeypatch
):
    python = tmp_path / "python.exe"
    python.touch()
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(
        "school_account_handoff.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({**_preflight_result(), "password": "not-for-ui"}),
            stderr="private diagnostic",
        ),
    )
    with pytest.raises(AccountHandoffError) as caught:
        _backend_preflight(
            tmp_path,
            {
                "workspace_id": WORKSPACE_ID,
                "database": "smhai_school_demo",
                "port": 3342,
            },
        )
    assert caught.value.code == "OWNER_CHECK_FAILED"
    assert "not-for-ui" not in str(caught.value)
    assert "private diagnostic" not in str(caught.value)


def _fake_modules(
    monkeypatch, workspace: Path, calls: list[str], *, credential_failure=False
):
    marker = {
        "workspace_id": WORKSPACE_ID,
        "database": "smhai_school_demo",
        "port": 3342,
    }
    private = {"recipe_version": "school-contexts-v1", "credentials": {}}
    credentials = {
        slot: {
            "username": f"SYNTHETIC_{slot.upper().replace('.', '_')}",
            "password": "synthetic-fixture-password",
        }
        for slot in SLOTS
    }

    def validate_workspace_path(path, _repo, *, allow_custom_name):
        calls.append("workspace")
        assert allow_custom_name is True
        return path

    def validate_credentials(value):
        calls.append("credentials")
        if credential_failure or value.get("recipe_version") != "school-contexts-v1":
            raise ValueError("private-value-must-not-escape")
        return credentials

    browser_qa = SimpleNamespace(
        ACCOUNT_SLOTS=SLOTS,
        HarnessError=ValueError,
        _read_workspace_marker=lambda _path: marker,
        validate_credentials=validate_credentials,
        validate_workspace_path=validate_workspace_path,
    )
    private_settings = SimpleNamespace(
        read_private=lambda _path: calls.append("read_private") or private
    )
    monkeypatch.setitem(sys.modules, "school_browser_qa", browser_qa)
    monkeypatch.setitem(sys.modules, "private_settings", private_settings)
    monkeypatch.setattr(
        "school_account_handoff._backend_preflight",
        lambda _workspace, _marker: calls.append("owner_preflight"),
    )
    monkeypatch.setattr(
        "school_account_handoff._verify_private_acl",
        lambda _workspace, _vault: calls.append("private_acl"),
    )
    return private, credentials


def test_load_accounts_checks_workspace_owner_and_acl_before_reading_vault(
    tmp_path, monkeypatch, capsys
):
    workspace = tmp_path / "external-workspace"
    workspace.mkdir()
    (workspace / "school-accounts.private.dpapi").write_bytes(
        b"synthetic-sealed-fixture"
    )
    calls = []
    private, expected = _fake_modules(monkeypatch, workspace, calls)
    monkeypatch.setattr("school_account_handoff.os.name", "nt")

    accounts = load_demo_accounts(str(workspace), WORKSPACE_ID)

    assert accounts == expected
    assert calls == [
        "workspace",
        "owner_preflight",
        "private_acl",
        "read_private",
        "credentials",
    ]
    assert private == {}
    output = capsys.readouterr().out
    assert output == ""
    assert "synthetic-fixture-password" not in output


def test_workspace_uuid_mismatch_fails_before_owner_or_vault_access(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "external-workspace"
    workspace.mkdir()
    (workspace / "school-accounts.private.dpapi").write_bytes(
        b"synthetic-sealed-fixture"
    )
    calls = []
    _fake_modules(monkeypatch, workspace, calls)
    monkeypatch.setattr("school_account_handoff.os.name", "nt")

    with pytest.raises(AccountHandoffError) as caught:
        load_demo_accounts(str(workspace), "11111111111111111111111111111111")
    assert caught.value.code == "WORKSPACE_ID_MISMATCH"
    assert calls == ["workspace"]


def test_acl_failure_fails_before_decrypting_vault(tmp_path, monkeypatch):
    workspace = tmp_path / "external-workspace"
    workspace.mkdir()
    (workspace / "school-accounts.private.dpapi").write_bytes(
        b"synthetic-sealed-fixture"
    )
    calls = []
    private, _ = _fake_modules(monkeypatch, workspace, calls)
    monkeypatch.setattr("school_account_handoff.os.name", "nt")
    monkeypatch.setattr(
        "school_account_handoff._verify_private_acl",
        lambda *_args: (_ for _ in ()).throw(
            AccountHandoffError("PRIVATE_DACL_REQUIRED")
        ),
    )

    with pytest.raises(AccountHandoffError) as caught:
        load_demo_accounts(str(workspace), WORKSPACE_ID)
    assert caught.value.code == "PRIVATE_DACL_REQUIRED"
    assert calls == ["workspace", "owner_preflight"]
    assert private["recipe_version"] == "school-contexts-v1"


def test_unknown_credential_recipe_is_closed_and_private_container_is_cleared(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "external-workspace"
    workspace.mkdir()
    (workspace / "school-accounts.private.dpapi").write_bytes(
        b"synthetic-sealed-fixture"
    )
    calls = []
    private, _ = _fake_modules(monkeypatch, workspace, calls, credential_failure=True)
    monkeypatch.setattr("school_account_handoff.os.name", "nt")

    with pytest.raises(AccountHandoffError) as caught:
        load_demo_accounts(str(workspace), WORKSPACE_ID)
    assert caught.value.code == "CREDENTIALS_UNAVAILABLE"
    assert private == {}


def test_non_windows_refuses_before_path_or_vault_access(monkeypatch):
    monkeypatch.setattr("school_account_handoff.os.name", "posix")
    with pytest.raises(AccountHandoffError) as caught:
        load_demo_accounts("not-a-path", WORKSPACE_ID)
    assert caught.value.code == "WINDOWS_REQUIRED"


def test_password_stays_hidden_until_clicked_and_clears_on_switch_and_close():
    class Var:
        def __init__(self):
            self.value = ""

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    class Widget:
        def __init__(self):
            self.options = {}

        def configure(self, **kwargs):
            self.options.update(kwargs)

    class Listbox(Widget):
        def __init__(self):
            super().__init__()
            self.selected = (0,)
            self.items = ["alpha.student", "alpha.teacher"]

        def curselection(self):
            return self.selected

        def get(self, index):
            return self.items[index]

        def delete(self, *_args):
            self.items.clear()

    class Root:
        destroyed = False

        def destroy(self):
            self.destroyed = True

    from school_account_handoff import AccountHandoffWindow

    window = object.__new__(AccountHandoffWindow)
    window._accounts = {
        "alpha.student": {
            "username": "SYNTHETIC_STUDENT",
            "password": "student-fixture-secret",
        },
        "alpha.teacher": {
            "username": "SYNTHETIC_TEACHER",
            "password": "teacher-fixture-secret",
        },
    }
    window._selected_slot = None
    window._visible = False
    window.password_var = Var()
    window.username_var = Var()
    window.password_entry = Widget()
    window.reveal_button = Widget()
    window.account_list = Listbox()
    window.workspace_var = Var()
    window.workspace_id_var = Var()
    window.root = Root()

    window.select_account()
    assert window.password_var.get() == ""
    assert window._selected_slot == "alpha.student"
    window.toggle_password()
    assert window.password_var.get() == "student-fixture-secret"
    assert window.password_entry.options["show"] == ""

    window.account_list.selected = (1,)
    window.select_account()
    assert window.password_var.get() == ""
    assert window.password_entry.options["show"] == "●"
    window.toggle_password()
    assert window.password_var.get() == "teacher-fixture-secret"

    window.close()
    assert window.password_var.get() == ""
    assert window.username_var.get() == ""
    assert window._accounts == {}
    assert window.root.destroyed is True


def test_acl_child_result_must_be_exact_and_private(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    vault = workspace / "school-accounts.private.dpapi"
    vault.write_bytes(b"synthetic-fixture")
    captured = {}

    def run(argv, **kwargs):
        captured["env"] = kwargs["env"]
        captured["creationflags"] = kwargs["creationflags"]
        return SimpleNamespace(
            returncode=0,
            stdout='{"workspace_private":true,"vault_private":true}',
            stderr="",
        )

    monkeypatch.setenv("DB_PASSWORD", "not-forwarded")
    monkeypatch.setattr("school_account_handoff.subprocess.run", run)
    _verify_private_acl(workspace, vault)
    assert "DB_PASSWORD" not in captured["env"]
    assert captured["creationflags"] == getattr(
        subprocess, "CREATE_NO_WINDOW", 0x08000000
    )

    monkeypatch.setattr(
        "school_account_handoff.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout='{"workspace_private":true,"vault_private":true,"extra":true}',
            stderr="",
        ),
    )
    with pytest.raises(AccountHandoffError) as caught:
        _verify_private_acl(workspace, vault)
    assert caught.value.code == "PRIVATE_DACL_REQUIRED"
