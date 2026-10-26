"""Loopback-only, pinned two-hop SSH forwarding for the vector API.

Private configuration is stored in .env.vector-tunnel.json. This helper never
copies key material or changes either remote machine's configuration.
"""

import argparse
import base64
import binascii
import json
from pathlib import Path
import re
import struct
import threading

ROOT = Path(__file__).resolve().parents[1]
LISTEN_PORT = 18082
TARGET_PORT = 8195
JUMP_PORT = 2222
FIELDS = {
    "ssh_host", "ssh_user", "key_file", "known_hosts", "second_key_file",
    "second_user", "second_host_key", "listen_port", "target_port",
}


def pinned_key_bytes(value):
    """Validate the complete SSH Ed25519 public-key wire format without SSH IO."""
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError("模型主機公鑰設定不正確")
    try:
        raw = base64.b64decode(value, validate=True)
        offset = 0
        fields = []
        for _ in range(2):
            if len(raw) < offset + 4:
                raise ValueError()
            length = struct.unpack(">I", raw[offset:offset + 4])[0]
            offset += 4
            if length > len(raw) - offset:
                raise ValueError()
            fields.append(raw[offset:offset + length])
            offset += length
        if fields[0] != b"ssh-ed25519" or len(fields[1]) != 32 or offset != len(raw):
            raise ValueError()
        return raw
    except (ValueError, binascii.Error, struct.error):
        raise ValueError("模型主機公鑰設定不正確") from None


def validate_config(config):
    if not isinstance(config, dict) or set(config) != FIELDS:
        raise ValueError("向量轉發設定欄位不正確")
    if type(config["listen_port"]) is not int or config["listen_port"] != LISTEN_PORT:
        raise ValueError("向量轉發僅允許指定的本機連接埠")
    if type(config["target_port"]) is not int or config["target_port"] != TARGET_PORT:
        raise ValueError("向量轉發僅允許指定的模型介面連接埠")
    for field in FIELDS - {"listen_port", "target_port"}:
        value = config[field]
        if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("向量轉發設定不完整")
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", config["ssh_host"]):
        raise ValueError("SSH 主機設定不正確")
    for field in ("ssh_user", "second_user"):
        if not re.fullmatch(r"[a-z_][a-z0-9_.-]{0,63}", config[field]):
            raise ValueError("SSH 使用者設定不正確")
    pinned_key_bytes(config["second_host_key"])
    return dict(config)


def load_config(path):
    return validate_config(json.loads(Path(path).read_text(encoding="utf-8")))


class VectorConnector:
    def __init__(self, config):
        self.config = validate_config(config)
        self.first = None
        self.second = None
        self.jump = None
        self.lock = threading.Lock()

    def _close(self):
        # Closing the target also closes its jump channel; every close is safe
        # to repeat, and no exception may prevent the gateway from being closed.
        for resource in (self.second, self.jump, self.first):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
        self.first = self.second = self.jump = None

    def _connect(self):
        # Paramiko is a host-only dependency, imported after offline validation.
        import paramiko

        first = second = jump = None
        try:
            first = paramiko.SSHClient()
            first.load_host_keys(self.config["known_hosts"])
            first.set_missing_host_key_policy(paramiko.RejectPolicy())
            first.connect(self.config["ssh_host"], username=self.config["ssh_user"],
                          key_filename=self.config["key_file"], look_for_keys=False,
                          allow_agent=False, timeout=15, auth_timeout=15, banner_timeout=15)
            first_transport = first.get_transport()
            if first_transport is None:
                raise RuntimeError("SSH 閘道尚未連接")
            first_transport.set_keepalive(30)
            jump = first_transport.open_channel("direct-tcpip", ("127.0.0.1", JUMP_PORT),
                                                ("127.0.0.1", 0), timeout=15)
            second = paramiko.SSHClient()
            key = paramiko.Ed25519Key(data=pinned_key_bytes(self.config["second_host_key"]))
            second.get_host_keys().add("[127.0.0.1]:2222", "ssh-ed25519", key)
            second.set_missing_host_key_policy(paramiko.RejectPolicy())
            second.connect("127.0.0.1", port=JUMP_PORT, username=self.config["second_user"],
                           key_filename=self.config["second_key_file"], sock=jump,
                           look_for_keys=False, allow_agent=False, timeout=15,
                           auth_timeout=15, banner_timeout=15)
            second_transport = second.get_transport()
            if second_transport is None:
                raise RuntimeError("模型主機尚未連接")
            second_transport.set_keepalive(30)
            self.first, self.second, self.jump = first, second, jump
        except Exception:
            for resource in (second, jump, first):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        pass
            raise

    def channel(self):
        with self.lock:
            first_transport = self.first.get_transport() if self.first else None
            second_transport = self.second.get_transport() if self.second else None
            if (not first_transport or not first_transport.is_active()
                    or not second_transport or not second_transport.is_active()):
                self._close()
                self._connect()
                second_transport = self.second.get_transport()
            try:
                return second_transport.open_channel("direct-tcpip", ("127.0.0.1", TARGET_PORT),
                                                     ("127.0.0.1", 0), timeout=15)
            except Exception:
                self._close()
                raise

    def close(self):
        with self.lock:
            self._close()


def main():
    from model_tunnel import serve

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / ".env.vector-tunnel.json")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        serve(config, connector=VectorConnector(config))
    except KeyboardInterrupt:
        return 0
    except Exception:
        print("向量轉發未能啟動；請檢查本機設定，憑證未輸出", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
