"""Run the real early guard in a disposable tree, before dependency/DB access."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class LegacyLauncherGuardTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell runtime unavailable")
    def test_school_revision_blocks_legacy_launcher_before_bootstrap(self):
        source = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            for name in ["start-demo.ps1", "demo-common.ps1"]:
                shutil.copyfile(source / "scripts" / name, root / "scripts" / name)
            shutil.copyfile(source / "start-demo.ps1", root / "start-demo.ps1")
            migration = root / "11_database/migrations/versions/20261011_0003_school_membership_context.py"
            migration.parent.mkdir(parents=True)
            migration.write_text("# disposable marker", encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(root / "start-demo.ps1"), "-PreflightOnly"], capture_output=True, text=True, timeout=20, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("legacy M0 launcher must not upgrade", result.stdout)
            self.assertNotIn("Missing command", result.stdout)
            self.assertFalse((root / ".autonomous").exists())


if __name__ == "__main__":
    unittest.main()
