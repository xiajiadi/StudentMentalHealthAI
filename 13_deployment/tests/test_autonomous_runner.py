"""Disposable local-state tests; no database, services, credentials or models."""
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("autonomous_runner", Path(__file__).parents[1] / "autonomous_runner.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Runner, TaskError = module.Runner, module.TaskError


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        queue = self.root / "14_docs/autonomous-delivery/TASK_QUEUE.json"
        queue.parent.mkdir(parents=True)
        tasks = [{"id": key, "status": "READY", "owner": None, "attempts": 0, "depends_on": deps, "priority": 10, "evidence": []} for key, deps in [("a", []), ("b", ["a"])]]
        queue.write_text(json.dumps({"baseline": "test", "max_attempts": 3, "tasks": tasks}), encoding="utf-8")
        (self.root / "proof.md").write_text("Disposable test evidence", encoding="utf-8")
        self.runner = Runner(self.root)
        head_patch = patch.object(Runner, 'head', return_value='test-commit')
        head_patch.start()
        self.addCleanup(head_patch.stop)
        clean_patch = patch.object(Runner, "require_clean")
        clean_patch.start()
        self.addCleanup(clean_patch.stop)
        self.clean_check = clean_patch

    def test_independent_review_and_integration(self):
        r = self.runner
        r.mutate("claim", "a", "worker")
        with self.assertRaises(TaskError):
            r.mutate("claim", "a", "other")
        r.mutate("evidence", "a", "worker", "proof.md", "pass", command="unittest synthetic")
        r.mutate("submit", "a", "worker")
        with self.assertRaises(TaskError):
            r.mutate("review", "a", "worker")
        r.mutate("review", "a", "qa")
        with self.assertRaises(TaskError):
            r.mutate("done", "a", "qa")
        r.mutate("evidence", "a", "qa", "proof.md", "pass", command="unittest synthetic")
        state = r.mutate("done", "a", "qa")
        self.assertTrue(r.eligible(state, r.task(state, "b")))

    def test_dependency_and_stop(self):
        with self.assertRaises(TaskError):
            self.runner.mutate("claim", "b", "worker")
        self.runner.mutate("stop")
        with self.assertRaises(TaskError):
            self.runner.mutate("claim", "a", "worker")
        self.runner.mutate("resume")
        self.runner.mutate("claim", "a", "worker")

    def test_failure_is_bounded(self):
        for _ in range(3):
            self.runner.mutate("claim", "a", "worker")
            state = self.runner.mutate("fail", "a", "worker")
        self.assertEqual(self.runner.task(state, "a")["status"], "BLOCKED")
        with self.assertRaises(TaskError):
            self.runner.mutate("claim", "a", "worker")

    def test_recovery_and_author_preserved(self):
        self.runner.mutate("claim", "a", "worker")
        self.runner.mutate("evidence", "a", "worker", "proof.md", "pass", command="unittest synthetic")
        state = self.runner.load()
        task = self.runner.task(state, "a")
        task["lease_until"] = time.time() - 1
        self.runner.save(state)
        state = self.runner.mutate("recover")
        self.assertEqual(self.runner.task(state, "a")["status"], "REVIEW")
        with self.assertRaises(TaskError):
            self.runner.mutate("review", "a", "worker")

    def test_recovery_without_evidence_requeues(self):
        self.runner.mutate("claim", "a", "worker", lease_seconds=-1)
        state = self.runner.mutate("recover")
        self.assertEqual(self.runner.task(state, "a")["status"], "READY")

    def test_exclusive_lock(self):
        with self.runner.locked():
            with self.assertRaises(TaskError):
                self.runner.mutate("stop")
        self.runner.mutate("stop")

    def test_evidence_path_escape_and_outcome(self):
        self.runner.mutate("claim", "a", "worker")
        for path in ["../outside.md", str(self.root / "proof.md"), "missing.md"]:
            with self.assertRaises(TaskError):
                self.runner.mutate("evidence", "a", "worker", path, "pass")
        with self.assertRaises(TaskError):
            self.runner.mutate("evidence", "a", "worker", "proof.md", "unknown")

    def test_failed_evidence_cannot_be_reviewed(self):
        self.runner.mutate("claim", "a", "worker")
        self.runner.mutate("evidence", "a", "worker", "proof.md", "fail", command="unittest synthetic")
        with self.assertRaises(TaskError):
            self.runner.mutate("submit", "a", "worker")

    def test_stale_attempt_pass_rejected(self):
        r = self.runner
        r.mutate("claim", "a", "worker")
        r.mutate("evidence", "a", "worker", "proof.md", "pass", command="unittest synthetic")
        r.mutate("fail", "a", "worker")
        r.mutate("claim", "a", "worker")
        with self.assertRaises(TaskError):
            r.mutate("submit", "a", "worker")

    def test_queue_drift_rejected(self):
        self.runner.mutate("stop")
        path = self.runner.queue_path
        data = json.loads(path.read_text(encoding="utf-8"))
        data["tasks"][0]["depends_on"] = ["b"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(TaskError):
            self.runner.load()

    def test_explicit_sync_invalidates_changed_definition(self):
        r = self.runner
        r.mutate("claim", "a", "worker")
        path = r.queue_path
        data = json.loads(path.read_text(encoding="utf-8"))
        data["tasks"][0]["title"] = "changed requirement"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(TaskError):
            r.sync_queue()
        state = json.loads(r.state_path.read_text(encoding="utf-8"))
        r.task(state, "a")["lease_until"] = 0
        r.save(state)
        state = r.sync_queue()
        self.assertEqual(r.task(state, "a")["attempts"], 0)
        self.assertIsNone(r.task(state, "a")["owner"])
        self.assertEqual(r.task(r.load(), "a")["title"], "changed requirement")

    def test_dirty_tree_blocks_done(self):
        r = self.runner
        r.mutate("claim", "a", "worker")
        r.mutate("evidence", "a", "worker", "proof.md", "pass", command="unittest synthetic")
        r.mutate("submit", "a", "worker")
        r.mutate("review", "a", "qa")
        r.mutate("evidence", "a", "qa", "proof.md", "pass", command="unittest synthetic")
        with patch.object(Runner, "require_clean", side_effect=TaskError("dirty")):
            with self.assertRaises(TaskError):
                r.mutate("done", "a", "qa")
        self.assertEqual(r.task(r.load(), "a")["status"], "INTEGRATING")

    def test_actual_git_worktree_check(self):
        import subprocess
        for args in [["init", "-q"], ["add", "proof.md"], ["-c", "user.name=Disposable Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"]]:
            subprocess.run(["git", *args], cwd=self.root, capture_output=True, check=True, timeout=10)
        self.clean_check.stop()
        state = {"baseline_untracked_artifacts": ["14_docs/"]}
        self.runner.require_clean(state)
        (self.root / "proof.md").write_text("dirty", encoding="utf-8")
        with self.assertRaises(TaskError):
            self.runner.require_clean(state)

    def test_changed_proof_or_commit_rejected(self):
        r = self.runner
        r.mutate("claim", "a", "worker")
        r.mutate("evidence", "a", "worker", "proof.md", "pass", command="unittest synthetic")
        (self.root / "proof.md").write_text("changed", encoding="utf-8")
        with self.assertRaises(TaskError):
            r.mutate("submit", "a", "worker")
        r.mutate("evidence", "a", "worker", "proof.md", "pass", command="unittest synthetic")
        with patch.object(Runner, "head", return_value="other-commit"):
            with self.assertRaises(TaskError):
                r.mutate("submit", "a", "worker")

    def test_reviewer_can_request_changes(self):
        r = self.runner
        r.mutate("claim", "a", "worker")
        r.mutate("evidence", "a", "worker", "proof.md", "pass", command="unittest synthetic")
        r.mutate("submit", "a", "worker")
        state = r.mutate("reject", "a", "qa")
        self.assertTrue(r.eligible(state, r.task(state, "a")))

    def test_process_exit_releases_kernel_lock(self):
        import subprocess
        import sys
        code = "import importlib.util, pathlib, os; s=importlib.util.spec_from_file_location('r', pathlib.Path(os.environ['RUNNER_FILE'])); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); r=m.Runner(pathlib.Path(os.environ['RUNNER_ROOT'])); lock=r.locked(); lock.__enter__(); print('locked', flush=True); os._exit(7)"
        import os
        env = dict(os.environ, RUNNER_FILE=str(Path(module.__file__)), RUNNER_ROOT=str(self.root))
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 7)
        self.assertIn("locked", result.stdout)
        self.runner.mutate("stop")

    def test_live_other_process_blocks(self):
        import subprocess
        import sys
        import os
        code = "import importlib.util, pathlib, os, time; s=importlib.util.spec_from_file_location('r', pathlib.Path(os.environ['RUNNER_FILE'])); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); r=m.Runner(pathlib.Path(os.environ['RUNNER_ROOT'])); lock=r.locked(); lock.__enter__(); print('locked', flush=True); time.sleep(15)"
        env = dict(os.environ, RUNNER_FILE=str(Path(module.__file__)), RUNNER_ROOT=str(self.root))
        process = subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            with self.assertRaises(TaskError):
                self.runner.mutate("stop")
        finally:
            process.terminate()
            process.wait(timeout=10)
            process.stdout.close()


if __name__ == "__main__":
    unittest.main()
