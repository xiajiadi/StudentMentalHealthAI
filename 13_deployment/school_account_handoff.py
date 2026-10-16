"""Local, current-user-only viewer for registered synthetic demo accounts."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
ACCOUNT_FILE = "school-accounts.private.dpapi"
_ACL_SCRIPT = r"""
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
function Test-AllowedAcl([string]$path, [bool]$requireProtected) {
  $acl = Get-Acl -LiteralPath $path -ErrorAction Stop
  $rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
  $unexpected = @($rules | Where-Object {
    $_.IdentityReference.Value -ne $sid -or
    $_.AccessControlType -ne 'Allow' -or
    ($_.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -ne [System.Security.AccessControl.FileSystemRights]::FullControl
  })
  $requirement = (-not $requireProtected) -or $acl.AreAccessRulesProtected
  return ($rules.Count -gt 0 -and $unexpected.Count -eq 0 -and $requirement)
}
$directoryOk = Test-AllowedAcl $env:PSYNOVA_ACCOUNT_WORKSPACE $true
$fileOk = Test-AllowedAcl $env:PSYNOVA_ACCOUNT_VAULT $false
@{workspace_private=$directoryOk; vault_private=$fileOk} | ConvertTo-Json -Compress
"""
_SAFE_MESSAGES = {
    "WINDOWS_REQUIRED": "此账号库只能在创建它的 Windows 用户会话中打开。",
    "WORKSPACE_INVALID": "Workspace 路径或登记信息无效。",
    "WORKSPACE_ID_MISMATCH": "输入的 Workspace UUID 与该目录不匹配。",
    "OWNER_CHECK_FAILED": "无法确认该 Workspace 的数据库 owner、权限或运行身份。",
    "PRIVATE_DACL_REQUIRED": "Workspace 或账号文件的访问控制不符合当前用户私有要求。",
    "CREDENTIALS_UNAVAILABLE": "未找到符合登记格式的合成演示账号。",
}


class AccountHandoffError(RuntimeError):
    """Closed error categories; never include a path, password, or child output."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _reject_reparse_components(path: Path) -> None:
    if not path.is_absolute():
        raise AccountHandoffError("WORKSPACE_INVALID")
    absolute = Path(os.path.abspath(path))
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    for component in reversed((absolute, *absolute.parents)):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise AccountHandoffError("WORKSPACE_INVALID") from None
        if getattr(metadata, "st_file_attributes", 0) & reparse_flag:
            raise AccountHandoffError("WORKSPACE_INVALID")


def _verify_private_acl(workspace: Path, vault: Path) -> None:
    base_environment = {
        key: os.environ[key]
        for key in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP")
        if isinstance(os.environ.get(key), str)
    }
    child_environment = {
        **base_environment,
        "PSYNOVA_ACCOUNT_WORKSPACE": str(workspace),
        "PSYNOVA_ACCOUNT_VAULT": str(vault),
    }
    try:
        child = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", _ACL_SCRIPT],
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            env=child_environment,
            text=True,
            timeout=10,
        )
        if child.returncode != 0:
            raise AccountHandoffError("PRIVATE_DACL_REQUIRED")
        result = json.loads(child.stdout)
        if (
            type(result) is not dict
            or set(result) != {"workspace_private", "vault_private"}
            or result.get("workspace_private") is not True
            or result.get("vault_private") is not True
        ):
            raise AccountHandoffError("PRIVATE_DACL_REQUIRED")
    except AccountHandoffError:
        raise
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        raise AccountHandoffError("PRIVATE_DACL_REQUIRED") from None
    finally:
        if "child" in locals():
            child.stdout = ""
            child.stderr = ""


def _normalized_workspace_id(value: str) -> str:
    if type(value) is not str:
        raise AccountHandoffError("WORKSPACE_ID_MISMATCH")
    try:
        return uuid.UUID(value.strip()).hex
    except (ValueError, AttributeError, TypeError):
        raise AccountHandoffError("WORKSPACE_ID_MISMATCH") from None


def _backend_preflight(workspace: Path, expected_marker: dict[str, Any]) -> None:
    executable = Path(sys.executable)
    if executable.name.casefold() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    if not executable.is_file():
        raise AccountHandoffError("OWNER_CHECK_FAILED")
    child_environment = {
        key: os.environ[key]
        for key in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "USERPROFILE")
        if isinstance(os.environ.get(key), str)
    }
    script = REPO / "13_deployment" / "school_backend.py"
    try:
        child = subprocess.run(
            [
                str(executable),
                str(script),
                "--workspace",
                str(workspace),
                "--preflight-only",
            ],
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            cwd=REPO,
            env=child_environment,
            text=True,
            timeout=45,
        )
        if child.returncode != 0:
            raise AccountHandoffError("OWNER_CHECK_FAILED")
        result = json.loads(child.stdout)
        expected_fields = {
            "database",
            "port",
            "workspace_id",
            "data_directory",
            "identity_profile",
            "schema_revision",
            "purpose",
            "scope",
            "preflight",
            "module_clients",
        }
        if (
            type(result) is not dict
            or set(result) != expected_fields
            or result.get("workspace_id") != expected_marker.get("workspace_id")
            or result.get("database") != expected_marker.get("database")
            or result.get("port") != expected_marker.get("port")
            or result.get("identity_profile") != "school_tenant"
            or result.get("purpose") != "application"
            or result.get("scope") != "APPLICATION_CURRENT_REVISION"
            or result.get("preflight") != "PASS"
            or result.get("module_clients") != "HTTP"
        ):
            raise AccountHandoffError("OWNER_CHECK_FAILED")
    except AccountHandoffError:
        raise
    except (OSError, subprocess.SubprocessError, TypeError, ValueError, KeyError):
        raise AccountHandoffError("OWNER_CHECK_FAILED") from None
    finally:
        if "child" in locals():
            child.stdout = ""
            child.stderr = ""


def load_demo_accounts(
    workspace_value: str, expected_workspace_id: str
) -> dict[str, dict[str, str]]:
    """Validate the owned workspace first, then decrypt only the registered alpha slots."""
    if os.name != "nt":
        raise AccountHandoffError("WINDOWS_REQUIRED")
    expected_id = _normalized_workspace_id(expected_workspace_id)
    try:
        requested = Path(workspace_value).expanduser()
        _reject_reparse_components(requested)
        workspace = requested.resolve(strict=True)
        if not workspace.is_dir():
            raise AccountHandoffError("WORKSPACE_INVALID")
        import school_browser_qa as browser_qa
        from private_settings import read_private

        try:
            workspace = browser_qa.validate_workspace_path(
                workspace, REPO, allow_custom_name=True
            )
        except browser_qa.HarnessError:
            raise AccountHandoffError("WORKSPACE_INVALID") from None
        marker = browser_qa._read_workspace_marker(workspace)
        if (
            type(marker) is not dict
            or _normalized_workspace_id(marker.get("workspace_id")) != expected_id
        ):
            raise AccountHandoffError("WORKSPACE_ID_MISMATCH")

        _backend_preflight(workspace, marker)

        marker_after_preflight = browser_qa._read_workspace_marker(workspace)
        if type(marker_after_preflight) is not dict or marker_after_preflight.get(
            "workspace_id"
        ) != marker.get("workspace_id"):
            raise AccountHandoffError("WORKSPACE_ID_MISMATCH")
        vault = workspace / ACCOUNT_FILE
        _reject_reparse_components(vault)
        if not vault.is_file():
            raise AccountHandoffError("CREDENTIALS_UNAVAILABLE")
        _verify_private_acl(workspace, vault)

        try:
            private = read_private(vault)
        except (OSError, TypeError, ValueError):
            raise AccountHandoffError("CREDENTIALS_UNAVAILABLE") from None
        try:
            credentials = browser_qa.validate_credentials(private)
        except (browser_qa.HarnessError, TypeError, ValueError):
            raise AccountHandoffError("CREDENTIALS_UNAVAILABLE") from None
        finally:
            private.clear()
        if (
            type(credentials) is not dict
            or set(credentials) != set(browser_qa.ACCOUNT_SLOTS)
            or any(
                type(item) is not dict
                or set(item) != {"username", "password"}
                or not item["username"].startswith("SYNTHETIC_")
                or not isinstance(item["password"], str)
                for item in credentials.values()
            )
        ):
            raise AccountHandoffError("CREDENTIALS_UNAVAILABLE")
        return credentials
    except AccountHandoffError:
        raise
    except (ImportError, OSError, RuntimeError, TypeError, ValueError, KeyError):
        raise AccountHandoffError("OWNER_CHECK_FAILED") from None


class AccountHandoffWindow:
    def __init__(self, root: Any, tk: Any, ttk: Any) -> None:
        self.root = root
        self.tk = tk
        self.ttk = ttk
        self._accounts: dict[str, dict[str, str]] = {}
        self._selected_slot: str | None = None
        self._visible = False

        root.title("合成学校演示账号")
        root.resizable(False, False)
        frame = ttk.Frame(root, padding=16)
        frame.grid(sticky="nsew")
        ttk.Label(frame, text="Workspace 绝对路径").grid(row=0, column=0, sticky="w")
        self.workspace_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.workspace_var, width=58).grid(
            row=1, column=0, sticky="ew", pady=(2, 10)
        )
        ttk.Label(frame, text="Workspace UUID").grid(row=2, column=0, sticky="w")
        self.workspace_id_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.workspace_id_var, width=58).grid(
            row=3, column=0, sticky="ew", pady=(2, 10)
        )
        self.verify_button = ttk.Button(
            frame, text="验证并读取合成账号", command=self.verify
        )
        self.verify_button.grid(row=4, column=0, sticky="w")
        self.status_var = tk.StringVar(value="输入 workspace 路径和 UUID 后再验证。")
        ttk.Label(frame, textvariable=self.status_var, wraplength=520).grid(
            row=5, column=0, sticky="w", pady=(8, 12)
        )
        self.account_list = tk.Listbox(frame, height=4, width=58, exportselection=False)
        self.account_list.grid(row=6, column=0, sticky="ew")
        self.account_list.bind("<<ListboxSelect>>", self.select_account)
        self.username_var = tk.StringVar()
        ttk.Label(frame, text="合成用户名").grid(
            row=7, column=0, sticky="w", pady=(10, 0)
        )
        ttk.Entry(
            frame, textvariable=self.username_var, state="readonly", width=58
        ).grid(row=8, column=0, sticky="ew", pady=(2, 8))
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(
            frame, textvariable=self.password_var, show="●", state="readonly", width=58
        )
        self.password_entry.grid(row=9, column=0, sticky="ew")
        self.reveal_button = ttk.Button(
            frame,
            text="显示所选账号密码",
            command=self.toggle_password,
            state="disabled",
        )
        self.reveal_button.grid(row=10, column=0, sticky="w", pady=(8, 0))
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _hide_password(self) -> None:
        self.password_var.set("")
        self.password_entry.configure(show="●")
        self._visible = False
        if hasattr(self, "reveal_button"):
            self.reveal_button.configure(text="显示所选账号密码")

    def _clear_accounts(self) -> None:
        self._hide_password()
        self.username_var.set("")
        for account in self._accounts.values():
            account["username"] = ""
            account["password"] = ""
        self._accounts.clear()
        self._selected_slot = None
        self.account_list.delete(0, "end")
        self.reveal_button.configure(state="disabled")

    def verify(self) -> None:
        self._clear_accounts()
        self.status_var.set("正在验证 workspace、owner 和私有访问控制…")
        self.root.update_idletasks()
        try:
            accounts = load_demo_accounts(
                self.workspace_var.get(), self.workspace_id_var.get()
            )
        except AccountHandoffError as exc:
            self.status_var.set(_SAFE_MESSAGES.get(exc.code, "无法验证账号库。"))
            return
        self._accounts = accounts
        for slot in accounts:
            self.account_list.insert("end", slot)
        self.status_var.set("验证完成。选择一个账号；密码默认隐藏。")

    def select_account(self, _event: Any = None) -> None:
        self._hide_password()
        selected = self.account_list.curselection()
        if not selected:
            self._selected_slot = None
            self.username_var.set("")
            self.reveal_button.configure(state="disabled")
            return
        slot = self.account_list.get(selected[0])
        account = self._accounts.get(slot)
        if account is None:
            self._selected_slot = None
            self.username_var.set("")
            self.reveal_button.configure(state="disabled")
            return
        self._selected_slot = slot
        self.username_var.set(account["username"])
        self.reveal_button.configure(state="normal")

    def toggle_password(self) -> None:
        if self._visible:
            self._hide_password()
            return
        account = self._accounts.get(self._selected_slot or "")
        if account is None:
            return
        self.password_var.set(account["password"])
        self.password_entry.configure(show="")
        self._visible = True
        self.reveal_button.configure(text="隐藏密码")

    def close(self) -> None:
        self._clear_accounts()
        self.workspace_var.set("")
        self.workspace_id_var.set("")
        self.root.destroy()


def main() -> int:
    if os.name != "nt":
        return 2
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        return 2
    try:
        root = tk.Tk()
    except (OSError, tk.TclError):
        return 2
    AccountHandoffWindow(root, tk, ttk)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
