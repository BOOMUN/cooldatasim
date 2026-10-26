import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("model_tunnel", ROOT / "scripts/model_tunnel.py")
tunnel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tunnel)


class ModelTunnelConfig(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.json"
        self.config = {"ssh_host": "gateway.invalid", "ssh_user": "test", "key_file": "private-key",
                       "known_hosts": "known-hosts", "listen_port": 18081, "target_port": 18000}

    def load(self):
        self.path.write_text(json.dumps(self.config), encoding="utf-8")
        return tunnel.load_config(self.path)

    def test_valid_local_forward_configuration(self):
        self.assertEqual(self.load(), self.config)

    def test_public_bind_cannot_be_configured(self):
        self.config["listen_host"] = "0.0.0.0"
        with self.assertRaises(ValueError):
            self.load()

    def test_arbitrary_remote_target_cannot_be_configured(self):
        self.config["target_host"] = "external.invalid"
        with self.assertRaises(ValueError):
            self.load()

    def test_bad_ports_are_rejected(self):
        for value in (True, 22, 65536, "18081"):
            self.config["listen_port"] = value
            with self.assertRaises(ValueError):
                self.load()


if __name__ == "__main__":
    unittest.main()
