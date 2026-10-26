import base64
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vector_tunnel", ROOT / "scripts/vector_tunnel.py")
tunnel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tunnel)


def public_key_blob(algorithm=b"ssh-ed25519", key=b"A" * 32):
    wire = struct.pack(">I", len(algorithm)) + algorithm + struct.pack(">I", len(key)) + key
    return base64.b64encode(wire).decode("ascii")


class VectorTunnelConfig(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.json"
        self.config = {
            "ssh_host": "gateway.invalid", "ssh_user": "ubuntu", "key_file": "gateway-key",
            "known_hosts": "known-hosts", "second_key_file": "model-key", "second_user": "ubuntu",
            "second_host_key": public_key_blob(), "listen_port": 18082, "target_port": 8195,
        }

    def load(self):
        self.path.write_text(json.dumps(self.config), encoding="utf-8")
        return tunnel.load_config(self.path)

    def test_complete_configuration(self):
        self.assertEqual(self.load(), self.config)

    def test_no_public_bind_or_arbitrary_target(self):
        for field in ("listen_host", "target_host"):
            config = {**self.config, field: "0.0.0.0"}
            with self.assertRaises(ValueError):
                tunnel.validate_config(config)

    def test_ports_are_fixed_and_boolean_is_not_a_port(self):
        for field in ("listen_port", "target_port"):
            for value in (True, "18082", 22, 65536):
                with self.assertRaises(ValueError):
                    tunnel.validate_config({**self.config, field: value})

    def test_bad_or_non_ed25519_pin_is_rejected(self):
        for value in ("not base64", public_key_blob(b"ssh-rsa"), public_key_blob(key=b"A" * 31),
                      public_key_blob() + "\n", base64.b64encode(b"short").decode()):
            with self.assertRaises(ValueError):
                tunnel.validate_config({**self.config, "second_host_key": value})

    def test_trailing_wire_data_is_rejected(self):
        raw = base64.b64decode(public_key_blob()) + b"unexpected"
        with self.assertRaises(ValueError):
            tunnel.pinned_key_bytes(base64.b64encode(raw).decode())

    def test_missing_fields_and_control_characters_are_rejected(self):
        broken = dict(self.config)
        broken.pop("second_key_file")
        with self.assertRaises(ValueError):
            tunnel.validate_config(broken)
        with self.assertRaises(ValueError):
            tunnel.validate_config({**self.config, "second_user": "ubuntu\nother"})

    def fake_ssh(self):
        library = MagicMock()
        first, second = MagicMock(), MagicMock()
        library.SSHClient.side_effect = [first, second]
        first.get_transport.return_value.is_active.return_value = True
        second.get_transport.return_value.is_active.return_value = True
        return library, first, second

    def test_gateway_and_target_use_strict_keys_and_expected_hops(self):
        library, first, second = self.fake_ssh()
        connector = tunnel.VectorConnector(self.config)
        with patch.dict(sys.modules, {"paramiko": library}):
            channel = connector.channel()
            self.assertIs(channel, second.get_transport.return_value.open_channel.return_value)
            first.load_host_keys.assert_called_once_with("known-hosts")
            self.assertEqual(library.RejectPolicy.call_count, 2)
            first.get_transport.return_value.open_channel.assert_called_once_with(
                "direct-tcpip", ("127.0.0.1", 2222), ("127.0.0.1", 0), timeout=15)
            second.get_host_keys.return_value.add.assert_called_once_with(
                "[127.0.0.1]:2222", "ssh-ed25519", library.Ed25519Key.return_value)
            library.Ed25519Key.assert_called_once_with(data=base64.b64decode(self.config["second_host_key"]))
            self.assertEqual(second.connect.call_args.kwargs["port"], 2222)
            self.assertFalse(second.connect.call_args.kwargs["allow_agent"])
            self.assertFalse(second.connect.call_args.kwargs["look_for_keys"])
            second.get_transport.return_value.open_channel.assert_called_once_with(
                "direct-tcpip", ("127.0.0.1", 8195), ("127.0.0.1", 0), timeout=15)
            first.get_transport.return_value.set_keepalive.assert_called_once_with(30)
            second.get_transport.return_value.set_keepalive.assert_called_once_with(30)
        connector.close()

    def test_channel_reuse_does_not_repeat_ssh_login(self):
        library, first, second = self.fake_ssh()
        connector = tunnel.VectorConnector(self.config)
        with patch.dict(sys.modules, {"paramiko": library}):
            connector.channel()
            connector.channel()
        self.assertEqual(library.SSHClient.call_count, 2)
        self.assertEqual(second.get_transport.return_value.open_channel.call_count, 2)
        connector.close()

    def test_failed_target_authentication_closes_both_hops(self):
        library, first, second = self.fake_ssh()
        second.connect.side_effect = RuntimeError("private failure detail")
        connector = tunnel.VectorConnector(self.config)
        with patch.dict(sys.modules, {"paramiko": library}):
            with self.assertRaises(RuntimeError):
                connector.channel()
        first.close.assert_called_once()
        second.close.assert_called_once()
        first.get_transport.return_value.open_channel.return_value.close.assert_called_once()
        self.assertIsNone(connector.first)
        self.assertIsNone(connector.second)

    def test_failed_model_channel_resets_connections(self):
        library, first, second = self.fake_ssh()
        second.get_transport.return_value.open_channel.side_effect = RuntimeError("refused")
        connector = tunnel.VectorConnector(self.config)
        with patch.dict(sys.modules, {"paramiko": library}):
            with self.assertRaises(RuntimeError):
                connector.channel()
        first.close.assert_called_once()
        second.close.assert_called_once()
        self.assertIsNone(connector.first)

    def test_dead_gateway_reconnects_both_hops(self):
        library, first, second = self.fake_ssh()
        next_first, next_second = MagicMock(), MagicMock()
        library.SSHClient.side_effect = [first, second, next_first, next_second]
        connector = tunnel.VectorConnector(self.config)
        with patch.dict(sys.modules, {"paramiko": library}):
            connector.channel()
            first.get_transport.return_value.is_active.return_value = False
            connector.channel()
        self.assertEqual(library.SSHClient.call_count, 4)
        first.close.assert_called_once()
        second.close.assert_called_once()
        self.assertIs(connector.second, next_second)
        connector.close()


if __name__ == "__main__":
    unittest.main()
