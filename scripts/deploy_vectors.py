"""Deploy only the dedicated Cool Data Sim CPU vector service over pinned SSH."""

import argparse
import hashlib
import json
from pathlib import Path
import secrets
import sys

from vector_tunnel import VectorConnector, load_config

ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = "/home/ubuntu/ai/workspace/cooldatasim-vector-api"
REMOTE_UNIT = "/home/ubuntu/.config/systemd/user/cooldatasim-vector-api.service"
RUNTIME = "/home/ubuntu/ai/workspace/employee-rag/.venv/bin/python"
MODEL_ROOT = "/home/ubuntu/ai/workspace/employee-rag/models"
SERVICE = "cooldatasim-vector-api.service"
MARKER = "cooldatasim-isolated-vector-api-v1"
SOURCES = ("vector_api.py", "inference.py")


def remote_call(client, command, timeout=30):
    _, out, err = client.exec_command(command, timeout=timeout)
    body = out.read()
    status = out.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"遠端操作失敗（狀態{status}）；未輸出憑證或原始日誌")
    return body


def exists(sftp, path):
    try:
        sftp.stat(path)
        return True
    except FileNotFoundError:
        return False


def put_private(sftp, path, content, mode=0o600):
    temporary = path + ".cooldatasim-upload"
    with sftp.open(temporary, "wb") as stream:
        stream.write(content)
    sftp.chmod(temporary, mode)
    sftp.posix_rename(temporary, path)


def local_environment(key):
    path = ROOT / ".env"
    original = path.read_text(encoding="utf-8")
    updates = {
        "COOLDATASIM_EMBEDDING_BASE_URL": "http://host.docker.internal:18082/v1",
        "COOLDATASIM_EMBEDDING_MODEL": "Qwen3-Embedding-0.6B",
        "COOLDATASIM_EMBEDDING_API_KEY": key,
        "COOLDATASIM_RERANKER_BASE_URL": "http://host.docker.internal:18082/v1",
        "COOLDATASIM_RERANKER_MODEL": "Qwen3-Reranker-0.6B",
        "COOLDATASIM_RERANKER_API_KEY": key,
    }
    lines, found = [], set()
    for line in original.splitlines():
        name = line.partition("=")[0]
        if name in updates:
            line = name + "=" + updates[name]
            found.add(name)
        lines.append(line)
    for name in updates.keys() - found:
        lines.append(name + "=" + updates[name])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def deploy(client):
    files = {name: (ROOT / "infra/vector-service" / name).read_bytes() for name in SOURCES}
    sftp = client.open_sftp()
    try:
        if exists(sftp, REMOTE_ROOT):
            if not exists(sftp, REMOTE_ROOT + "/.owner"):
                raise RuntimeError("遠端目錄已存在且不屬於本任務，未覆寫")
            with sftp.open(REMOTE_ROOT + "/.owner", "r") as stream:
                if stream.read().decode().strip() != MARKER:
                    raise RuntimeError("遠端目錄識別不符，未覆寫")
        else:
            sftp.mkdir(REMOTE_ROOT, mode=0o700)
            put_private(sftp, REMOTE_ROOT + "/.owner", (MARKER + "\n").encode())
        if exists(sftp, REMOTE_UNIT):
            with sftp.open(REMOTE_UNIT, "r") as stream:
                if "Description=Cool Data Sim isolated CPU vector API" not in stream.read().decode():
                    raise RuntimeError("服務單元名稱已被其他服務使用，未覆寫")
        key = None
        if exists(sftp, REMOTE_ROOT + "/.env"):
            with sftp.open(REMOTE_ROOT + "/.env", "r") as stream:
                settings = dict(line.split("=", 1) for line in stream.read().decode().splitlines() if "=" in line)
            key = settings.get("VECTOR_API_KEY")
        key = key or secrets.token_urlsafe(32)
        if len(key) < 32 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in key):
            raise RuntimeError("獨立服務憑證格式不正確，未輸出內容")
        environment = {
            "VECTOR_API_KEY": key, "VECTOR_MODEL_ROOT": MODEL_ROOT,
            "VECTOR_CPU_THREADS": "8", "VECTOR_MAX_TOKENS": "2048", "VECTOR_DTYPE": "bfloat16",
            "CUDA_VISIBLE_DEVICES": "", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
        }
        put_private(sftp, REMOTE_ROOT + "/.env", "".join(f"{k}={v}\n" for k, v in environment.items()).encode())
        for name, content in files.items():
            put_private(sftp, REMOTE_ROOT + "/" + name, content)
        manifest = {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}
        put_private(sftp, REMOTE_ROOT + "/source-manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
        unit = f"""[Unit]
Description=Cool Data Sim isolated CPU vector API
After=network.target

[Service]
Type=simple
WorkingDirectory={REMOTE_ROOT}
EnvironmentFile={REMOTE_ROOT}/.env
ExecStart={RUNTIME} -m uvicorn vector_api:app --host 127.0.0.1 --port 8195 --workers 1 --no-access-log
Restart=on-failure
RestartSec=5
TimeoutStartSec=180
MemoryMax=8G
CPUWeight=50
NoNewPrivileges=true
UMask=0077

[Install]
WantedBy=default.target
"""
        put_private(sftp, REMOTE_UNIT, unit.encode())
    finally:
        sftp.close()
    remote_call(client, f"{RUNTIME} -m py_compile {REMOTE_ROOT}/vector_api.py {REMOTE_ROOT}/inference.py")
    remote_call(client, "systemctl --user daemon-reload")
    remote_call(client, f"systemctl --user enable {SERVICE}")
    remote_call(client, f"systemctl --user restart {SERVICE}")
    local_environment(key)
    print("獨立CPU向量服務已安裝並啟動；本機設定已寫入，待真實接口驗證。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("deploy", "status"))
    args = parser.parse_args()
    connector = None
    try:
        connector = VectorConnector(load_config(ROOT / ".env.vector-tunnel.json"))
        connector._connect()
        if args.command == "deploy":
            deploy(connector.second)
        else:
            result = remote_call(connector.second, f"systemctl --user is-active {SERVICE}")
            print("向量服務狀態：", result.decode().strip())
    except Exception as exc:
        print(f"向量部署操作未完成（{type(exc).__name__}）；憑證與原始錯誤未輸出。")
        if isinstance(exc, RuntimeError):
            print(str(exc))
        return 1
    finally:
        if connector:
            connector.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
