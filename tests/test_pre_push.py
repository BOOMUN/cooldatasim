import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pre_push", ROOT / "scripts/pre_push.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)
PROJECT_SPEC = importlib.util.spec_from_file_location("handoff_project", ROOT / "scripts/project.py")
project = importlib.util.module_from_spec(PROJECT_SPEC)
PROJECT_SPEC.loader.exec_module(project)


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

    def test_zip_inside_another_repository_does_not_change_parent_hooks(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            subprocess.run(["git", "init", "-q", str(parent)], check=True)
            child = parent / "unzipped-source"
            child.mkdir()
            self.assertFalse(project.install_git_hooks(child))
            result = subprocess.run(["git", "config", "--local", "--get", "core.hooksPath"], cwd=parent, capture_output=True)
            self.assertNotEqual(result.returncode, 0)

    def test_custom_hook_configuration_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "config", "--local", "core.hooksPath", "custom-hooks"], cwd=root, check=True)
            self.assertFalse(project.install_git_hooks(root))
            result = subprocess.run(["git", "config", "--get", "core.hooksPath"], cwd=root, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), "custom-hooks")
