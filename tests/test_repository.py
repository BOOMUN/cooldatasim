"""Failure-path tests for repository safety and document checks."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("project", REPO / "scripts/project.py")
project = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(project)


class RepositoryChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in project.MANAGED_FILES:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((REPO / name).read_bytes())

    def errors(self):
        return project.collect_errors(self.root)

    def test_clean_foundation(self):
        self.assertEqual(self.errors(), [])

    def test_missing_entry_fails(self):
        (self.root / "AGENTS.md").unlink()
        self.assertTrue(any("AGENTS.md" in error for error in self.errors()))

    def test_broken_document_link_fails(self):
        path = self.root / "README.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n[broken](docs/missing.md)\n", encoding="utf-8")
        self.assertTrue(any("broken local document link" in error for error in self.errors()))

    def test_task_without_scope_fails(self):
        path = self.root / "docs/TASKS/TASK-001.md"
        text = path.read_text(encoding="utf-8").replace("## 允许修改", "## 无范围")
        path.write_text(text, encoding="utf-8")
        self.assertTrue(any("allowlist" in error for error in self.errors()))

    def test_out_of_scope_task_file_fails(self):
        text = (self.root / "docs/TASKS/TASK-001.md").read_text(encoding="utf-8")
        text = text.replace("- `README.md`", "- `README.md`\n- `server/production.env`")
        self.assertTrue(project.task_errors(text))

    def test_deployment_task_has_separate_scope(self):
        text = (self.root / "docs/TASKS/TASK-002.md").read_text(encoding="utf-8")
        self.assertEqual(project.task_errors(text, project.DEPLOYMENT_SCOPE), [])
        self.assertTrue(project.task_errors(text))

    def test_traditional_task_headings_are_supported(self):
        text = (self.root / "docs/TASKS/TASK-004.md").read_text(encoding="utf-8")
        self.assertEqual(project.task_errors(text, None), [])

    def test_private_key_detection_does_not_echo_value(self):
        marker = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
        errors = project.secret_errors(marker + "\nDUMMY_PRIVATE_VALUE", "notes.txt")
        self.assertTrue(errors)
        self.assertNotIn("DUMMY_PRIVATE_VALUE", " ".join(errors))

    def test_api_token_detection(self):
        token = "sk-" + "A" * 30
        self.assertTrue(project.secret_errors(token, "notes.txt"))

    def test_environment_credentials_must_be_empty(self):
        self.assertTrue(project.secret_errors("TEST_API_KEY=dummy\n", ".env.example"))
        self.assertEqual(project.secret_errors("TEST_API_KEY=\n", ".env.example"), [])

    def test_sensitive_tracked_file_names(self):
        for name in (".env", ".env.production", "auth/server.key", "cert.pem", "id_ed25519"):
            self.assertTrue(project.sensitive_name(name), name)
        self.assertFalse(project.sensitive_name(".env.example"))

    def test_path_escape_rejected(self):
        for name in ("../outside.md", "/etc/passwd", "C:/outside", "docs\\outside"):
            with self.assertRaises(ValueError):
                project.safe_path(self.root, name)

    def test_formatter_is_idempotent_and_normalizes_lines(self):
        path = self.root / "README.md"
        text = path.read_text(encoding="utf-8")
        path.write_bytes((text.replace("\n", "  \r\n")).encode("utf-8"))
        self.assertIn("README.md", project.format_files(self.root))
        self.assertEqual(project.format_files(self.root), [])
        self.assertEqual(self.errors(), [])

    def test_formatter_does_not_change_python_literals(self):
        path = self.root / "scripts/project.py"
        text = 'value = """literal with significant spaces  \n"""\n'
        path.write_text(text, encoding="utf-8")
        with self.assertRaises(ValueError):
            project.format_files(self.root)
        self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_invalid_python_fails(self):
        (self.root / "scripts/project.py").write_text("def broken(\n", encoding="utf-8")
        self.assertTrue(any("syntax error" in error for error in self.errors()))

    def test_git_scan_failure_is_not_silently_successful(self):
        (self.root / ".git").mkdir()
        with patch.object(project.subprocess, "run", side_effect=subprocess.SubprocessError):
            self.assertTrue(any("incomplete" in error for error in self.errors()))

    def test_additional_untracked_file_is_scanned(self):
        (self.root / ".git").mkdir()
        (self.root / "notes.txt").write_text("sk-" + "B" * 30 + "\n", encoding="utf-8")
        result = subprocess.CompletedProcess([], 0, stdout=b"notes.txt\0")
        with patch.object(project.subprocess, "run", return_value=result):
            self.assertTrue(any("notes.txt: possible API" in error for error in self.errors()))


if __name__ == "__main__":
    unittest.main()
