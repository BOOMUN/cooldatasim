import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("package_git", ROOT / "scripts/package_git.py")
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


class GitHandoff(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        package.git(self.root, "init", "-b", "ai/TASK-005")
        package.git(self.root, "config", "user.name", "Fixture")
        package.git(self.root, "config", "user.email", "fixture@example.invalid")
        for name in ("AGENTS.md", "README.md", "docs/ARCHITECTURE.md", "docs/RUNBOOK.md", ".env.example"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n", encoding="utf-8")
        (self.root / ".gitignore").write_text(".env\noutputs/\n", encoding="utf-8")

    def commit(self):
        package.git(self.root, "add", "--all")
        package.git(self.root, "commit", "-m", "fixture")

    def test_bundle_and_zip_can_be_restored_without_runtime_env(self):
        (self.root / ".env").write_text("PRIVATE_API_KEY=" + "x" * 35 + "\n", encoding="utf-8")
        self.commit()
        target = package.export(self.root)
        manifest = json.loads((target / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["offline_clone_verified"])
        with zipfile.ZipFile(target / "cooldatasim-source.zip") as archive:
            self.assertIn("cooldatasim/AGENTS.md", archive.namelist())
            self.assertNotIn("cooldatasim/.env", archive.namelist())

    def test_dirty_worktree_is_not_exported(self):
        self.commit()
        (self.root / "new.md").write_text("uncommitted\n")
        with self.assertRaisesRegex(RuntimeError, "尚未全部提交"):
            package.export(self.root)

    def test_known_secret_is_rejected_without_echo(self):
        value = "private-local-value-" + "Z" * 24
        (self.root / ".env").write_text("TEST_API_KEY=" + value, encoding="utf-8")
        (self.root / "notes.md").write_text(value, encoding="utf-8")
        with self.assertRaises(ValueError) as result:
            package.audit(self.root)
        self.assertNotIn(value, str(result.exception))

    def test_staged_secret_is_caught_even_when_working_copy_is_clean(self):
        value = "sk-" + "T" * 35
        path = self.root / "bad.txt"
        path.write_text(value)
        package.git(self.root, "add", "bad.txt")
        path.write_text("clean now\n")
        with self.assertRaises(ValueError):
            package.audit(self.root)

    def test_removed_secret_in_history_is_not_bundled(self):
        path = self.root / "old.txt"
        path.write_text("sk-" + "U" * 35)
        self.commit()
        path.unlink()
        self.commit()
        with self.assertRaises(ValueError):
            package.audit(self.root)

    def test_runtime_paths_are_blocked_case_insensitively(self):
        for name in (".ENV", ".env.production", "keys/A.PEM", "outputs/archive.txt", "node_modules/pkg/index.js", "db.sqlite"):
            self.assertTrue(package.forbidden_name(name), name)
        self.assertFalse(package.forbidden_name(".env.example"))


if __name__ == "__main__":
    unittest.main()
