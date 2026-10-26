"""Local database tooling tests; no Docker or network access."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("local_db", REPO / "scripts/local_db.py")
db = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(db)


class LocalDatabaseTools(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".env.example").write_bytes((REPO / ".env.example").read_bytes())

    def test_credentials_are_distinct_and_not_printed(self):
        with patch("builtins.print") as output:
            db.init_env(self.root)
        values = db.env_values(self.root)
        self.assertNotEqual(values["COOLDATASIM_DB_ADMIN_PASSWORD"], values["COOLDATASIM_DB_APP_PASSWORD"])
        for name in ("COOLDATASIM_DB_ADMIN_PASSWORD", "COOLDATASIM_DB_APP_PASSWORD"):
            self.assertNotIn(values[name], str(output.call_args_list))

    def test_existing_env_is_never_overwritten(self):
        (self.root / ".env").write_text("existing=keep\n")
        with self.assertRaises(FileExistsError):
            db.init_env(self.root)
        self.assertEqual((self.root / ".env").read_text(), "existing=keep\n")

    def test_missing_example_field_does_not_write_partial_env(self):
        (self.root / ".env.example").write_text("COOLDATASIM_DB_PORT=5433\n")
        with self.assertRaises(ValueError):
            db.init_env(self.root)
        self.assertFalse((self.root / ".env").exists())

    def test_invalid_port_rejected(self):
        db.init_env(self.root)
        path = self.root / ".env"
        text = path.read_text(encoding="utf-8").replace("COOLDATASIM_DB_PORT=5433", "COOLDATASIM_DB_PORT=80")
        path.write_text(text, encoding="utf-8")
        with self.assertRaises(ValueError):
            db.env_values(self.root)

    def test_package_allowlist_excludes_credentials_and_data(self):
        self.assertNotIn(".env", db.SCHEMA_FILES)
        self.assertTrue(all(not name.startswith("outputs/") for name in db.SCHEMA_FILES))

    def test_compose_command_is_project_scoped(self):
        args = db.compose("stop", "postgres")
        self.assertIn("--project-name", args)
        self.assertIn("cooldatasim", args)
        self.assertNotIn("--volumes", args)

    def test_failed_docker_does_not_echo_sensitive_stderr(self):
        result = db.subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"sensitive-value")
        with patch.object(db, "local_docker_env", return_value={}), patch.object(db.subprocess, "run", return_value=result):
            with self.assertRaises(RuntimeError) as caught:
                db.execute(["docker", "compose", "config"])
        self.assertNotIn("sensitive-value", str(caught.exception))

    def test_remote_host_rejected_before_docker_execution(self):
        with patch.dict(db.os.environ, {"DOCKER_HOST": "ssh://example.invalid"}, clear=True):
            with patch.object(db.subprocess, "run") as run:
                with self.assertRaises(RuntimeError):
                    db.local_docker_env()
                run.assert_not_called()

    def test_remote_saved_context_rejected(self):
        result = db.subprocess.CompletedProcess([], 0, stdout=b'"tcp://example.invalid:2376"')
        with patch.dict(db.os.environ, {}, clear=True), patch.object(db.subprocess, "run", return_value=result):
            with self.assertRaises(RuntimeError):
                db.local_docker_env()

    def test_remote_windows_named_pipe_rejected(self):
        result = db.subprocess.CompletedProcess([], 0, stdout=b'"npipe:////remote-host/pipe/docker_engine"')
        with patch.dict(db.os.environ, {}, clear=True), patch.object(db.subprocess, "run", return_value=result):
            with self.assertRaises(RuntimeError):
                db.local_docker_env()

    def test_verified_endpoint_is_pinned(self):
        result = db.subprocess.CompletedProcess([], 0, stdout=b'"unix:///var/run/docker.sock"')
        with patch.dict(db.os.environ, {"DOCKER_CONTEXT": "local-example"}, clear=True):
            with patch.object(db.subprocess, "run", return_value=result):
                environ = db.local_docker_env()
        self.assertEqual(environ["DOCKER_HOST"], "unix:///var/run/docker.sock")
        self.assertNotIn("DOCKER_CONTEXT", environ)


if __name__ == "__main__":
    unittest.main()
