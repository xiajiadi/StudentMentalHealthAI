"""Validate initializer boundaries without initializing or connecting a DB."""
import importlib.util
import secrets
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location("school_workspace", Path(__file__).parents[1] / "create_school_workspace.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class WorkspaceBoundaryTests(unittest.TestCase):
    def test_existing_or_repository_path_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for target in [root, root / "data"]:
                with self.assertRaises(module.WorkspaceError):
                    module.validate_target(target, root, 3308)

    def test_system_or_legacy_ports_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for port in [3306, 3307, 0, 65536]:
                with self.assertRaises(module.WorkspaceError):
                    module.validate_target(root / "new", root / "repo", port)

    def test_occupied_port_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            probe = MagicMock()
            probe.__enter__.return_value = probe
            probe.bind.side_effect = OSError("synthetic occupied port")
            exclusive = getattr(module.socket, "SO_EXCLUSIVEADDRUSE", 0x100)
            with (
                patch.object(
                    module.socket, "SO_EXCLUSIVEADDRUSE", exclusive, create=True
                ),
                patch.object(module.socket, "socket", return_value=probe),
                self.assertRaises(module.WorkspaceError),
            ):
                module.validate_target(root / "new", root / "repo", 3308)
            probe.setsockopt.assert_called_once_with(
                module.socket.SOL_SOCKET, exclusive, 1
            )
            probe.bind.assert_called_once_with(("127.0.0.1", 3308))

    def test_sql_is_only_for_generated_identity_and_new_schema(self):
        sql = module.setup_sql(secrets.token_hex(32), secrets.token_hex(32))
        self.assertNotIn("smhai_m0_demo", sql)
        self.assertNotIn("DROP", sql)
        self.assertNotIn("*.*", sql)
        self.assertIn("smhai_school_demo", sql)
        with self.assertRaises(module.WorkspaceError):
            module.setup_sql("unexpected input", secrets.token_hex(32))

    @unittest.skipUnless(module.os.name == "nt", "Windows ACL required")
    def test_actual_acl_is_current_user_only(self):
        with tempfile.TemporaryDirectory() as directory:
            module.protect_directory(Path(directory))

    @unittest.skipUnless(module.os.name == "nt", "Windows DPAPI required")
    def test_private_settings_roundtrip_without_plaintext_storage(self):
        from private_settings import read_private, write_private
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.private.dpapi"
            value = secrets.token_hex(32)
            write_private(path, {"generated": value})
            self.assertTrue(value.encode() not in path.read_bytes())
            self.assertTrue(read_private(path).get("generated") == value)

if __name__ == "__main__":
    unittest.main()
