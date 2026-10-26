"""Manage only the local Cool Data Sim database; never connect to AWS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "cooldatasim-postgres:17-pgvector-v1"
PROJECT = "cooldatasim"
VOLUME = "cooldatasim_postgres-data"
CONTAINER = "cooldatasim-postgres-1"
SCHEMA_FILES = ("compose.yaml", ".env.example", "scripts/local_db.py")


def env_values(root: Path) -> dict[str, str]:
    result = {}
    for line in (root / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    for key in ("COOLDATASIM_DB_ADMIN_PASSWORD", "COOLDATASIM_DB_APP_PASSWORD"):
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", result.get(key, "")):
            raise ValueError("Database credentials must be 32-128 URL-safe characters; value withheld")
    if result["COOLDATASIM_DB_ADMIN_PASSWORD"] == result["COOLDATASIM_DB_APP_PASSWORD"]:
        raise ValueError("Admin and application credentials must differ")
    port = result.get("COOLDATASIM_DB_PORT", "5433")
    if not port.isdecimal() or not 1024 <= int(port) <= 65535:
        raise ValueError("Database port must be an integer in 1024..65535")
    return result


def init_env(root: Path) -> None:
    target = root / ".env"
    # Exclusive creation protects both existing credentials and symlink targets.
    text = (root / ".env.example").read_text(encoding="utf-8")
    admin, app = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    replacements = {
        "COOLDATASIM_DB_ADMIN_PASSWORD": admin,
        "COOLDATASIM_DB_APP_PASSWORD": app,
        "COOLDATASIM_DATABASE_URL": f"postgresql://cooldatasim_app:{app}@127.0.0.1:5433/cooldatasim",
    }
    lines = []
    found = set()
    for line in text.splitlines():
        key = line.partition("=")[0]
        if key in replacements:
            line = key + "=" + replacements[key]
            found.add(key)
        lines.append(line)
    if found != replacements.keys():
        raise ValueError("Environment example is missing required database fields")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines) + "\n")
    print("Created local .env with distinct random credentials; values are not displayed.")


def local_docker_env() -> dict[str, str]:
    """Resolve local configuration only; never contact a remote Docker endpoint."""
    environ = {k: v for k, v in os.environ.items()
               if not k.startswith(("COMPOSE_", "COOLDATASIM_DB_"))}
    host = environ.get("DOCKER_HOST", "")
    local_prefixes = ("npipe:////./pipe/", "unix:///")
    if host and not host.startswith(local_prefixes):
        raise RuntimeError("Remote Docker endpoints are outside this local deployment task")
    context = environ.get("DOCKER_CONTEXT")
    command = ["docker", "context", "inspect"]
    if context:
        command.append(context)
    command.extend(["--format", "{{json .Endpoints.docker.Host}}"])
    result = subprocess.run(command, capture_output=True, env=environ, timeout=15)
    if result.returncode:
        raise RuntimeError("Cannot verify local Docker context")
    endpoint = json.loads(result.stdout)
    # An explicit context takes precedence over DOCKER_HOST in the CLI.
    if host and not context:
        endpoint = host
    if not isinstance(endpoint, str) or not endpoint.startswith(local_prefixes):
        raise RuntimeError("Selected Docker context is remote; refusing this operation")
    environ.pop("DOCKER_CONTEXT", None)
    environ["DOCKER_HOST"] = endpoint
    return environ


def execute(args: list[str], *, root: Path = ROOT, stdin: bytes | None = None,
            output=None, timeout: int = 180, check: bool = True) -> subprocess.CompletedProcess:
    environ = local_docker_env()
    result = subprocess.run(args, cwd=root, input=stdin, stdout=output or subprocess.PIPE,
                            stderr=subprocess.PIPE, env=environ, timeout=timeout)
    if check and result.returncode:
        # Docker errors can contain configuration values. Do not echo commands/env.
        raise RuntimeError(f"{args[0]} operation failed (exit {result.returncode}); inspect local service safely")
    return result


def compose(*args: str) -> list[str]:
    return ["docker", "compose", "--project-name", PROJECT, "--project-directory", str(ROOT),
            "--env-file", str(ROOT / ".env"), "-f", str(ROOT / "compose.yaml"), *args]


def inspect_resource(kind: str, name: str) -> dict | None:
    result = execute(["docker", kind, "inspect", name], check=False)
    if result.returncode:
        # Distinguish an absent resource from a dead Docker engine.
        execute(["docker", "info", "--format", "{{.OSType}}"])
        return None
    return json.loads(result.stdout)[0]


def preflight() -> None:
    values = env_values(ROOT)
    for kind, name in (("container", CONTAINER), ("volume", VOLUME)):
        item = inspect_resource(kind, name)
        if item:
            labels = item.get("Config", {}).get("Labels", {}) if kind == "container" else item.get("Labels", {})
            if (labels or {}).get("com.cooldatasim.owner") != PROJECT:
                raise RuntimeError(f"Refusing to reuse unrecognized {kind}: {name}")
    existing = inspect_resource("container", CONTAINER)
    if not existing or not existing.get("State", {}).get("Running"):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", int(values.get("COOLDATASIM_DB_PORT", "5433"))))
    execute(compose("config", "--quiet"))


def sql(statement: str, *, wrong_password: bool = False) -> subprocess.CompletedProcess:
    # Credential is expanded inside the container, never passed in host arguments.
    password = "deliberately-invalid-test-password" if wrong_password else "$COOLDATASIM_DB_APP_PASSWORD"
    command = f'export PGPASSWORD="{password}"; exec psql -X -h 127.0.0.1 -U cooldatasim_app -d cooldatasim -v ON_ERROR_STOP=1 -At'
    return execute(compose("exec", "-T", "postgres", "sh", "-c", command),
                   stdin=statement.encode("utf-8"), check=not wrong_password)


def verify() -> None:
    env_values(ROOT)
    item = inspect_resource("container", CONTAINER)
    if not item or item.get("State", {}).get("Health", {}).get("Status") != "healthy":
        raise RuntimeError("Project database is not healthy")
    bindings = item["HostConfig"]["PortBindings"]["5432/tcp"]
    if any(binding["HostIp"] != "127.0.0.1" for binding in bindings):
        raise RuntimeError("Database is not restricted to loopback")
    if not any(m.get("Name") == VOLUME and m.get("Destination") == "/var/lib/postgresql/data"
               for m in item.get("Mounts", [])):
        raise RuntimeError("Expected project data volume is not mounted")
    statement = """
SELECT current_database(), current_user, current_setting('server_version');
SELECT extversion FROM pg_extension WHERE extname='vector';
SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user;
BEGIN;
CREATE TEMP TABLE vector_probe (id integer, embedding vector(1024));
INSERT INTO vector_probe VALUES (1, (ARRAY[1::real] || array_fill(0::real, ARRAY[1023]))::vector);
SELECT id, vector_dims(embedding), round((embedding <=> embedding)::numeric, 6) FROM vector_probe;
ROLLBACK;
"""
    text = sql(statement).stdout.decode("utf-8")
    if "1|1024|0.000000" not in text or "f|f|f" not in text:
        raise RuntimeError("Vector dimension/distance or application privilege check failed")
    denied = sql("SELECT 1;", wrong_password=True)
    if denied.returncode == 0 or b"password authentication failed" not in denied.stderr:
        raise RuntimeError("Incorrect credentials were not explicitly rejected")
    print(text.strip())
    print("PASS: health, application TCP authentication, wrong-password rejection, 1024D vector,")
    print("      non-superuser application role, loopback binding and named data volume.")


def artifact_dir(kind: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    path = ROOT / "outputs" / kind / stamp
    path.mkdir(parents=True, exist_ok=False)
    return path


def backup() -> None:
    env_values(ROOT)
    directory = artifact_dir("backups")
    partial = directory / "cooldatasim.dump.partial"
    with partial.open("xb") as stream:
        execute(compose("exec", "-T", "postgres", "pg_dump", "-U", "cooldatasim_admin",
                        "-d", "cooldatasim", "--format=custom"), output=stream)
    if partial.stat().st_size < 100:
        raise RuntimeError("Backup archive is unexpectedly small")
    # Validate archive structure without restoring or touching live tables.
    execute(compose("exec", "-T", "postgres", "pg_restore", "--list"), stdin=partial.read_bytes())
    final = partial.with_suffix("")
    partial.rename(final)
    print(f"Backup saved and archive listing verified: {final}")
    print("Full restore is not implied by this check. Keep backups separate from image packages.")


def package() -> None:
    directory = artifact_dir("releases")
    image_info = inspect_resource("image", IMAGE)
    if not image_info or image_info.get("Architecture") != "amd64" or image_info.get("Os") != "linux":
        raise RuntimeError("Build the linux/amd64 project database image first")
    partial = directory / "database-image.tar.partial"
    execute(["docker", "image", "save", "--output", str(partial), IMAGE], timeout=600)
    partial.rename(directory / "database-image.tar")
    for name in SCHEMA_FILES:
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    instructions = """Cool Data Sim database image package (linux/amd64)
This package contains the database image and startup configuration only.
It contains NO .env, passwords, application code, or database volume data.
On an authorized x86_64 AWS host with Docker Compose and Python 3.11+:
1. Verify SHA256SUMS.json against every package file.
2. docker image load --input database-image.tar
3. python3 scripts/local_db.py init-env
4. python3 scripts/local_db.py up
5. python3 scripts/local_db.py verify
New host credentials are generated locally. Do not reuse development passwords.
Database backup and attachments require a separate controlled transfer and restore task.
The port remains bound to 127.0.0.1. Do not expose PostgreSQL to the Internet.
This package does not deploy the customer service application or the Qwen models.
"""
    (directory / "MIGRATION.txt").write_text(instructions, encoding="utf-8", newline="\n")
    hashes = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            with path.open("rb") as stream:
                hashes[path.relative_to(directory).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {"project": PROJECT, "platform": "linux/amd64", "image": IMAGE,
                "image_id": image_info["Id"], "files": hashes}
    (directory / "SHA256SUMS.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Image package exported without data or credentials: {directory}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init-env", "build", "up", "status", "verify", "backup", "package", "stop"))
    command = parser.parse_args().command
    try:
        if command == "init-env":
            init_env(ROOT)
        elif command == "build":
            execute(["docker", "build", "--platform=linux/amd64", "--tag", IMAGE,
                     str(ROOT / "infra/postgres")], timeout=600)
            print(f"Built {IMAGE} for linux/amd64")
        elif command == "up":
            preflight()
            execute(compose("up", "-d", "--wait", "--wait-timeout", "120"), timeout=150)
            print("Project database started; run verify for authentication and vector checks.")
        elif command == "status":
            item = inspect_resource("container", CONTAINER)
            print("not created" if not item else json.dumps({
                "name": CONTAINER, "state": item["State"]["Status"],
                "health": item["State"].get("Health", {}).get("Status"),
                "ports": item["HostConfig"]["PortBindings"],
            }, indent=2))
        elif command == "verify":
            verify()
        elif command == "backup":
            backup()
        elif command == "package":
            package()
        elif command == "stop":
            preflight()
            execute(compose("stop", "postgres"))
            print("Stopped only this project's database; data volume retained.")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        # Exception detail may contain library outputs. Print only approved messages.
        print(f"FAILED: {type(exc).__name__}. No credentials printed; operation not reported as successful.")
        if isinstance(exc, (ValueError, RuntimeError)):
            print(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
