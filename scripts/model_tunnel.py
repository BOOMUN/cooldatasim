"""Loopback-only SSH forwarding to an existing model gateway.

Private configuration lives in .env.qwen-tunnel.json, never in the image or Git.
SSH host keys must already be trusted in the user's known_hosts file.
"""

import argparse
import json
from pathlib import Path
import select
import socketserver
import threading

ROOT = Path(__file__).resolve().parents[1]


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {"ssh_host", "ssh_user", "key_file", "known_hosts", "listen_port", "target_port"}
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError("SSH 轉發設定欄位不正確")
    for field in ("listen_port", "target_port"):
        if type(config[field]) is not int or not 1024 <= config[field] <= 65535:
            raise ValueError("SSH 轉發連接埠不正確")
    for field in ("ssh_host", "ssh_user", "key_file", "known_hosts"):
        if not isinstance(config[field], str) or not config[field].strip():
            raise ValueError("SSH 轉發設定不完整")
    return config


class Connector:
    def __init__(self, config):
        self.config = config
        self.client = None
        self.lock = threading.Lock()

    def channel(self):
        # Imported only at runtime; application containers never need SSH keys.
        import paramiko

        with self.lock:
            transport = self.client.get_transport() if self.client else None
            if not transport or not transport.is_active():
                if self.client:
                    self.client.close()
                client = paramiko.SSHClient()
                client.load_host_keys(self.config["known_hosts"])
                client.set_missing_host_key_policy(paramiko.RejectPolicy())
                try:
                    client.connect(self.config["ssh_host"], username=self.config["ssh_user"],
                                   key_filename=self.config["key_file"], look_for_keys=False,
                                   allow_agent=False, timeout=15, auth_timeout=15, banner_timeout=15)
                except Exception:
                    client.close()
                    raise
                transport = client.get_transport()
                transport.set_keepalive(30)
                self.client = client
            return transport.open_channel("direct-tcpip", ("127.0.0.1", self.config["target_port"]),
                                          ("127.0.0.1", 0), timeout=15)

    def close(self):
        with self.lock:
            if self.client:
                self.client.close()
                self.client = None


class Forwarder(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(config, connector=None):
    if connector is None:
        connector = Connector(config)

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            channel = None
            try:
                channel = connector.channel()
                while True:
                    ready, _, _ = select.select([self.request, channel], [], [], 180)
                    if not ready:
                        break
                    for source in ready:
                        data = source.recv(65536)
                        if not data:
                            return
                        (channel if source is self.request else self.request).sendall(data)
            except Exception:
                # Do not print SSH errors, key paths, headers or request contents.
                print("模型轉發連線失敗；未輸出憑證或請求內容", flush=True)
            finally:
                if channel:
                    channel.close()

    # Never listen on public/LAN interfaces and never accept arbitrary target hosts.
    try:
        with Forwarder(("127.0.0.1", config["listen_port"]), Handler) as server:
            print(f"模型轉發已監聽本機連接埠 {config['listen_port']}", flush=True)
            server.serve_forever()
    finally:
        connector.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / ".env.qwen-tunnel.json")
    args = parser.parse_args()
    try:
        serve(load_config(args.config))
    except KeyboardInterrupt:
        return 0
    except Exception:
        print("模型轉發未能啟動；請檢查本機設定與連接埠，憑證未輸出", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
