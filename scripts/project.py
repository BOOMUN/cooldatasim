"""Offline checks for the repository foundation, not business acceptance tests."""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION_FILES = (
    "README.md",
    "AGENTS.md",
    ".gitignore",
    ".env.example",
    "docs/REQUIREMENTS.md",
    "docs/ARCHITECTURE.md",
    "docs/RUNBOOK.md",
    "docs/AI_PROMPTS.md",
    "docs/TASKS/README.md",
    "docs/TASKS/_TEMPLATE.md",
    "docs/TASKS/TASK-001.md",
    "docs/DECISIONS/README.md",
    "docs/DECISIONS/ADR-001-model-boundaries.md",
    "docs/DECISIONS/ADR-002-whatsapp-channel.md",
    "docs/DECISIONS/ADR-003-stack.md",
    "scripts/project.py",
    "tests/test_repository.py",
    ".github/workflows/ci.yml",
    ".github/pull_request_template.md",
)
DEPLOYMENT_FILES = (
    "docs/TASKS/TASK-002.md",
    "docs/DECISIONS/ADR-004-local-containers.md",
    "scripts/local_db.py",
    "tests/test_local_db.py",
    "compose.yaml",
    "infra/postgres/Dockerfile",
    "infra/postgres/001-init.sql",
)
DEPLOYMENT_SCOPE = (
    "README.md", "AGENTS.md", ".env.example", "docs/REQUIREMENTS.md",
    "docs/ARCHITECTURE.md", "docs/RUNBOOK.md", "docs/TASKS/README.md",
    "docs/DECISIONS/README.md", "scripts/project.py", "tests/test_repository.py",
    *DEPLOYMENT_FILES,
)
APPLICATION_FILES = (
    "docs/TASKS/TASK-003.md", "docs/API.md",
    "docs/DECISIONS/ADR-005-initial-app.md", "scripts/app.py", ".dockerignore",
    "backend/requirements.txt", "backend/requirements.lock", "backend/Dockerfile",
)
VECTOR_FILES = (
    "docs/TASKS/TASK-004.md", "docs/DECISIONS/ADR-006-vector-service.md",
    "scripts/vector_tunnel.py", "scripts/deploy_vectors.py", "tests/test_vector_tunnel.py",
    "infra/vector-service/vector_api.py", "infra/vector-service/inference.py",
    "infra/vector-service/README.md", "infra/vector-service/test_vector_api.py",
    "infra/vector-service/cooldatasim-vector-api.service.example",
)
HANDOFF_FILES = (
    "docs/TASKS/TASK-005.md", "docs/HANDOFF.md", ".gitattributes",
    "scripts/package_git.py", "tests/test_package_git.py", ".githooks/pre-push",
    "scripts/pre_push.py", "tests/test_pre_push.py",
)
MANAGED_FILES = FOUNDATION_FILES + DEPLOYMENT_FILES + APPLICATION_FILES + VECTOR_FILES + HANDOFF_FILES
REVIEWED_BINARY_FILES = {"frontend/public/logo.png": b"\x89PNG\r\n\x1a\n"}
TASK_SECTIONS = (
    "状态", "背景", "验收标准", "允许修改", "禁止修改", "操作权限",
    "执行计划", "验证命令", "验证结果", "人工验收与风险",
)
TRADITIONAL_TASK_SECTIONS = {
    "状态": "狀態", "验收标准": "驗收標準", "允许修改": "允許修改",
    "操作权限": "操作權限", "执行计划": "執行計劃", "验证命令": "驗證命令",
    "验证结果": "驗證結果", "人工验收与风险": "人工驗收與風險",
}
MAX_SCAN_BYTES = 2 * 1024 * 1024


def safe_path(root: Path, name: str) -> Path:
    """Reject absolute paths, traversal and symlinks before any read or write."""
    parts = PurePosixPath(name).parts
    if not parts or ".." in parts or ":" in name or "\\" in name:
        raise ValueError("unsafe relative path")
    if PurePosixPath(name).is_absolute():
        raise ValueError("absolute path")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("symlink is not allowed")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("path outside repository")
    return path


def canonical(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()).rstrip() + "\n"


def task_errors(text: str, expected: tuple[str, ...] | None = FOUNDATION_FILES) -> list[str]:
    errors = []
    for section in TASK_SECTIONS:
        names = (section, TRADITIONAL_TASK_SECTIONS.get(section, section))
        if not any(re.search(r"^## " + re.escape(name) + r"$", text, re.M) for name in names):
            errors.append(f"missing task section: {section}")
    match = re.search(r"^## (?:允许修改|允許修改)\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    allowed = re.findall(r"^- `([^`]+)`$", match.group(1), re.M) if match else []
    if expected is None:
        if not match or not re.findall(r"`([^`]+)`", match.group(1)):
            errors.append("task requires an explicit path scope")
    elif set(allowed) != set(expected) or len(allowed) != len(set(allowed)):
        errors.append("task allowlist must match its own file manifest exactly")
    return errors


def sensitive_name(name: str) -> bool:
    path = PurePosixPath(name)
    base = path.name.lower()
    return (
        (base == ".env" or base.startswith(".env.")) and base != ".env.example"
        or path.suffix.lower() in {".key", ".pem", ".p12", ".pfx", ".jks"}
        or base.startswith(("id_rsa", "id_ed25519", "remote_access_ed25519"))
        or ".ssh" in path.parts
        or "secrets" in path.parts
    )


def secret_errors(text: str, name: str) -> list[str]:
    """Report locations/categories only; never return matched credential values."""
    errors = []
    private_marker = r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"
    api_marker = r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,})\b"
    if re.search(private_marker, text):
        errors.append(f"{name}: private key marker detected (value withheld)")
    if re.search(api_marker, text):
        errors.append(f"{name}: possible API credential detected (value withheld)")
    if PurePosixPath(name).name == ".env.example":
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if re.search(r"(?:KEY|TOKEN|SECRET|PASSWORD)$", key.strip(), re.I) and value.strip():
                errors.append(f"{name}: credential example fields must be blank")
    return errors


def candidate_files(root: Path) -> tuple[set[str], list[str]]:
    names = set(MANAGED_FILES)
    if not (root / ".git").exists():
        return names, []
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root, capture_output=True, check=True, timeout=20,
        )
        names.update(p for p in result.stdout.decode("utf-8").split("\0") if p)
        return names, []
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return names, ["could not enumerate Git files; credential scan is incomplete"]


def collect_errors(root: Path) -> list[str]:
    errors = []
    for name in MANAGED_FILES:
        try:
            path = safe_path(root, name)
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeError, ValueError):
            errors.append(f"{name}: missing, unreadable, non-UTF-8 or unsafe file")
            continue
        if raw != canonical(text).encode("utf-8"):
            errors.append(f"{name}: non-canonical whitespace; run fmt")
        if not text.strip():
            errors.append(f"{name}: empty file")
        if name.endswith(".py"):
            try:
                ast.parse(text, filename=name)
            except SyntaxError as exc:
                errors.append(f"{name}: Python syntax error at line {exc.lineno}")
        if name.endswith(".md"):
            for target in re.findall(r"\[[^\]\n]*\]\(([^)\s]+)\)", text):
                if re.match(r"[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
                    continue
                destination = (path.parent / target.split("#", 1)[0]).resolve()
                if not destination.is_relative_to(root.resolve()) or not destination.is_file():
                    errors.append(f"{name}: broken local document link")
        if name == "docs/TASKS/TASK-001.md":
            errors.extend(f"{name}: {error}" for error in task_errors(text))
        if name == "docs/TASKS/TASK-002.md":
            errors.extend(f"{name}: {error}" for error in task_errors(text, DEPLOYMENT_SCOPE))
        if name == "docs/TASKS/TASK-003.md":
            errors.extend(f"{name}: {error}" for error in task_errors(text, None))
        if name == "docs/TASKS/TASK-004.md":
            errors.extend(f"{name}: {error}" for error in task_errors(text, None))
        if name == "docs/TASKS/TASK-005.md":
            errors.extend(f"{name}: {error}" for error in task_errors(text, None))

    names, enumeration_errors = candidate_files(root)
    errors.extend(enumeration_errors)
    for name in sorted(names):
        if sensitive_name(name):
            errors.append(f"{name}: sensitive file must not be tracked or submitted")
            continue
        try:
            path = safe_path(root, name)
            if not path.is_file():
                errors.append(f"{name}: expected a regular file")
                continue
            if path.stat().st_size > MAX_SCAN_BYTES:
                errors.append(f"{name}: too large for this checker; review before expanding scope")
                continue
            raw = path.read_bytes()
            if name in REVIEWED_BINARY_FILES and raw.startswith(REVIEWED_BINARY_FILES[name]):
                continue
            if b"\x00" in raw:
                errors.append(f"{name}: binary file requires explicit review")
                continue
            text = raw.decode("utf-8")
            errors.extend(secret_errors(text, name))
            if name.endswith(".py"):
                try:
                    ast.parse(text, filename=name)
                except SyntaxError:
                    errors.append(f"{name}: invalid Python syntax")
            if PurePosixPath(name).name in {"package.json", "package-lock.json"}:
                try:
                    json.loads(text)
                except ValueError:
                    errors.append(f"{name}: invalid JSON")
        except (OSError, UnicodeError, ValueError):
            errors.append(f"{name}: scan failed; no success may be claimed")
    return errors


def format_files(root: Path) -> list[str]:
    changed = []
    for name in MANAGED_FILES:
        path = safe_path(root, name)
        original = path.read_bytes()
        text = original.decode("utf-8")
        normalized = canonical(text)
        # Formatting must not change Python string literals or other semantics.
        if name.endswith(".py"):
            before = ast.dump(ast.parse(text), include_attributes=False)
            after = ast.dump(ast.parse(normalized), include_attributes=False)
            if before != after:
                raise ValueError(f"{name}: whitespace changes Python semantics; format manually")
        result = normalized.encode("utf-8")
        if result != original:
            path.write_bytes(result)
            changed.append(name)
    return changed


def environment_check() -> int:
    if sys.version_info < (3, 11):
        print("ERROR: Python 3.11+ is required")
        return 1
    if not shutil.which("git"):
        print("ERROR: Git must be available on PATH")
        return 1
    print("OK: Python 3.11+ and Git available.")
    return 0


def venv_python(root: Path) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def npm(root: Path, *args: str) -> int:
    executable = shutil.which("npm")
    if not executable:
        print("ERROR: Node.js 24 and npm are required")
        return 1
    return subprocess.run([executable, *args], cwd=root / "frontend", check=False).returncode


def install() -> int:
    if environment_check():
        return 1
    python = venv_python(ROOT)
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True)
    result = subprocess.run([str(python), "-m", "pip", "install", "-r", "backend/requirements.lock"], cwd=ROOT)
    if result.returncode:
        return result.returncode
    install_git_hooks(ROOT)
    return npm(ROOT, "ci")


def install_git_hooks(root: Path) -> bool:
    location = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root, capture_output=True, text=True)
    if location.returncode or Path(location.stdout.strip()).resolve() != root.resolve():
        print("NOTICE: source archive has no own Git metadata; local hook setup skipped")
        return False
    hooks = subprocess.run(["git", "config", "--get", "core.hooksPath"], cwd=root, capture_output=True, text=True)
    if hooks.returncode or hooks.stdout.strip() == ".githooks":
        subprocess.run(["git", "config", "--local", "core.hooksPath", ".githooks"], cwd=root, check=True)
        print("OK: local protected-branch and force-push guard enabled")
        return True
    else:
        print("NOTICE: existing custom Git hooks preserved; integrate .githooks/pre-push manually")
        return False


def lint(root: Path) -> int:
    errors = collect_errors(root)
    for error in errors:
        print("ERROR:", error)
    if errors:
        return 1
    print(f"OK: {len(MANAGED_FILES)} required files and Git-visible source files checked.")
    return 0


def test(root: Path) -> int:
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py")
    if suite.countTestCases() == 0:
        print("ERROR: no tests found")
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    python = venv_python(root)
    if not python.exists():
        print("ERROR: run install before backend tests; business tests were not executed")
        return 1
    return subprocess.run([str(python), "-m", "pytest", "-c", "backend/pytest.ini", "backend/tests",
                           "infra/vector-service/test_vector_api.py", "-q"], cwd=root).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "lint", "test", "fmt", "check"))
    command = parser.parse_args().command
    if command == "install":
        return install()
    if command == "lint":
        return lint(ROOT)
    if command == "test":
        return test(ROOT)
    if command == "fmt":
        try:
            changed = format_files(ROOT)
        except (OSError, UnicodeError, ValueError, SyntaxError) as exc:
            print(f"ERROR: formatting stopped ({type(exc).__name__}); inspect files and rerun lint")
            return 1
        print(f"OK: formatted {len(changed)} foundation files")
        return 0
    return environment_check() or lint(ROOT) or test(ROOT) or npm(ROOT, "test") or npm(ROOT, "run", "build")


if __name__ == "__main__":
    raise SystemExit(main())
