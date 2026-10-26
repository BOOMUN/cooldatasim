import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pre_push", ROOT / "scripts/pre_push.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class PushGuard(unittest.TestCase):
    def update(self, branch="ai/TASK-005", old="b" * 40, new="a" * 40):
        return [f"refs/heads/{branch} {new} refs/heads/{branch} {old}"]

    def test_protected_branch_push_rejected(self):
        for branch in ("main", "master"):
            self.assertIsNotNone(guard.check_updates(self.update(branch)))

    def test_new_task_branch_allowed_without_network(self):
        runner = Mock()
        self.assertIsNone(guard.check_updates(self.update(old="0" * 40), runner))
        runner.assert_not_called()

    def test_fast_forward_allowed(self):
        runner = Mock(return_value=subprocess.CompletedProcess([], 0))
        self.assertIsNone(guard.check_updates(self.update(), runner))
        self.assertEqual(runner.call_args.args[0][:3], ["git", "merge-base", "--is-ancestor"])

    def test_force_push_or_missing_remote_object_rejected(self):
        for code in (1, 128):
            runner = Mock(return_value=subprocess.CompletedProcess([], code))
            self.assertIsNotNone(guard.check_updates(self.update(), runner))

    def test_protected_branch_deletion_rejected(self):
        self.assertIsNotNone(guard.check_updates(self.update(branch="main", new="0" * 40)))

    def test_tag_rewrite_rejected(self):
        line = f"refs/tags/v0.1.0 {'a'*40} refs/tags/v0.1.0 {'b'*40}"
        self.assertIsNotNone(guard.check_updates([line]))
