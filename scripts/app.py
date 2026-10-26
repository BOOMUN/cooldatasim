"""Build and run the local application. Credentials are never printed."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import local_db as db

ROOT = Path(__file__).resolve().parents[1]
APP_IMAGE = "cooldatasim-app:0.1.0"


def ensure_vector_forwarder():
    config = ROOT / ".env.vector-tunnel.json"
    if not config.exists():
        return
    pid_file = ROOT / ".env.vector-tunnel.pid"
    try:
        with socket.create_connection(("127.0.0.1", 18082), timeout=1):
            if not pid_file.exists():
                raise RuntimeError("向量轉發端口已使用，但沒有本專案進程記錄")
            pid = int(pid_file.read_text().strip())
            if sys.platform == "win32":
                query = (f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}';"
                         "if($p -and $p.CommandLine -match 'vector_tunnel[.]py'){exit 0}else{exit 1}")
                result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", query],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode:
                    raise RuntimeError("向量轉發進程識別不符，請檢查本機端口")
            else:
                result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True)
                if result.returncode or b"vector_tunnel.py" not in result.stdout:
                    raise RuntimeError("向量轉發進程識別不符，請檢查本機端口")
            return
    except (ConnectionError, TimeoutError):
        pass
    candidates = list(dict.fromkeys([sys.executable, shutil.which("python")]))
    python = None
    for candidate in candidates:
        if candidate and subprocess.run([candidate, "-c", "import paramiko"],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            python = candidate
            break
    if python is None:
        raise RuntimeError("宿主Python需要Paramiko才能啟動私有模型連線，請依RUNBOOK安裝")
    logs = ROOT / "outputs" / "vector-tunnel"
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / "stdout.log").open("ab") as out, (logs / "stderr.log").open("ab") as err:
        process = subprocess.Popen([python, "-u", str(ROOT / "scripts/vector_tunnel.py")],
                                   cwd=ROOT, stdout=out, stderr=err,
                                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                                   start_new_session=sys.platform != "win32")
    pid_file.write_text(str(process.pid) + "\n", encoding="utf-8")
    for _ in range(30):
        if process.poll() is not None:
            raise RuntimeError("向量轉發未啟動，請檢查本機私有設定")
        try:
            with socket.create_connection(("127.0.0.1", 18082), timeout=0.2):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("向量轉發啟動逾時，未宣告模型已接通")


def prepare():
    db.env_values(ROOT)
    path = ROOT / ".env"
    original = path.read_text(encoding="utf-8")
    current = dict(line.split("=", 1) for line in original.splitlines() if "=" in line and not line.startswith("#"))
    defaults = {"COOLDATASIM_ADMIN_USERNAME": "admin", "COOLDATASIM_ADMIN_PASSWORD": secrets.token_urlsafe(24),
                "COOLDATASIM_APP_PORT": "8787", "COOLDATASIM_WEBHOOK_SECRET": secrets.token_urlsafe(32)}
    lines = []
    for line in original.splitlines():
        key = line.partition("=")[0]
        if key in defaults and not current.get(key):
            line = key + "=" + defaults[key]
        lines.append(line)
    for key, value in defaults.items():
        if key not in current:
            lines.append(key + "=" + value)
    result = "\n".join(lines) + "\n"
    # Only app-specific missing fields are changed; existing DB credentials remain intact.
    if result != original:
        path.write_text(result, encoding="utf-8", newline="\n")
    print("Local application credentials prepared in ignored .env; values withheld.")


def app_preflight():
    values = db.env_values(ROOT)
    if len(values.get("COOLDATASIM_ADMIN_PASSWORD", "")) < 16:
        raise RuntimeError("Run prepare before starting the application")
    for name in ("cooldatasim-api-1", "cooldatasim-worker-1"):
        item = db.inspect_resource("container", name)
        if item and (item.get("Config", {}).get("Labels") or {}).get("com.cooldatasim.owner") != "cooldatasim":
            raise RuntimeError("Refusing to replace an unrecognized container")


def verify():
    values = db.env_values(ROOT)
    port = int(values.get("COOLDATASIM_APP_PORT", "8787"))
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=10) as response:
        payload = json.load(response)
    if payload.get("status") != "ok":
        raise RuntimeError("Application health check failed")
    for name in ("cooldatasim-api-1", "cooldatasim-worker-1"):
        item = db.inspect_resource("container", name)
        if not item or not item["State"]["Running"]:
            raise RuntimeError("Application or worker is not running")
    print(f"Application and worker running. Open http://127.0.0.1:{port}/")
    print("This is not proof of Qwen availability or WhatsApp live delivery.")


def package():
    directory = db.artifact_dir("app-releases")
    images = [APP_IMAGE, db.IMAGE]
    for image in images:
        item = db.inspect_resource("image", image)
        if not item or item.get("Architecture") != "amd64":
            raise RuntimeError("Build both project images before packaging")
    partial = directory / "images.tar.partial"
    db.execute(["docker", "image", "save", "-o", str(partial), *images], timeout=600)
    partial.rename(directory / "images.tar")
    for name in ("compose.yaml", ".env.example", "scripts/local_db.py", "scripts/app.py",
                 "scripts/vector_tunnel.py", "scripts/model_tunnel.py"):
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    note = """Cool Data Sim local application image package, linux/amd64.
No credentials, database data, attachments or model weights are included.
After approval on the target machine:
  docker image load -i images.tar
  python3 scripts/local_db.py init-env
  python3 scripts/app.py prepare
  python3 scripts/app.py up
  python3 scripts/app.py verify
Read credentials locally from .env. Data restore is a separate authorized procedure.
The site listens on loopback only; public TLS, models and WhatsApp require separate setup.
First-release external message sending is disabled. Do not call this a validated production release.
"""
    (directory / "MIGRATION.txt").write_text(note, encoding="utf-8", newline="\n")
    hashes = {}
    for path in directory.rglob("*"):
        if path.is_file():
            with path.open("rb") as stream:
                hashes[path.relative_to(directory).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    (directory / "SHA256SUMS.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "build", "up", "verify", "stop", "package"))
    command = parser.parse_args().command
    try:
        if command == "prepare":
            prepare()
        elif command == "build":
            db.execute(["docker", "build", "--platform=linux/amd64", "-f", "backend/Dockerfile", "-t", APP_IMAGE, "."], timeout=900)
            print("Built local application image (API, UI and worker).")
        elif command == "up":
            app_preflight()
            ensure_vector_forwarder()
            db.preflight()
            db.execute(db.compose("--profile", "app", "up", "-d", "--wait", "--wait-timeout", "120"), timeout=180)
            print("Application containers started; run verify and application acceptance tests.")
        elif command == "stop":
            app_preflight()
            db.execute(db.compose("--profile", "app", "stop", "api", "worker"))
        elif command == "verify":
            verify()
        elif command == "package":
            package()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Operation failed: {type(exc).__name__}; credentials and raw subprocess output withheld.")
        if isinstance(exc, RuntimeError):
            print(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
