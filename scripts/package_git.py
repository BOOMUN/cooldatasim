"""Audit and export source-only Git handoff files without runtime credentials."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
                 "outputs", "tmp", "dist", ".inspect-relaydesk", ".ssh", "secrets"}
REVIEWED_BINARY = {"frontend/public/logo.png": b"\x89PNG\r\n\x1a\n"}
MAX_BYTES = 2 * 1024 * 1024


def git(root, *args, input=None, check=True):
    result = subprocess.run(["git", *args], cwd=root, input=input, capture_output=True)
    if check and result.returncode:
        raise RuntimeError("Git操作失败；原始输出未回显，请检查仓库状态")
    return result


def forbidden_name(name):
    path = PurePosixPath(name)
    lower = path.name.lower()
    return (any(part.lower() in BLOCKED_PARTS for part in path.parts)
            or ((lower == ".env" or lower.startswith(".env.")) and lower != ".env.example")
            or path.suffix.lower() in {".key", ".pem", ".pfx", ".p12", ".jks", ".db", ".sqlite", ".sqlite3", ".tar", ".bundle", ".zip", ".log"}
            or lower.startswith(("id_rsa", "id_ed25519", "remote_access_ed25519")))


def local_secrets(root):
    """Use only sufficiently long known local values, never print them."""
    path = root / ".env"
    values = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip("\"'")
            if re.search(r"KEY|SECRET|TOKEN|PASSWORD", key, re.I) and len(value) >= 12:
                values.add(value.encode("utf-8"))
    return values


def content_errors(name, data, secrets=()):
    errors = []
    if forbidden_name(name):
        errors.append(f"{name}: 禁止包含运行文件或敏感文件")
        return errors
    if len(data) > MAX_BYTES:
        return [f"{name}: 超出源代码审查大小上限"]
    if any(value in data for value in secrets):
        errors.append(f"{name}: 包含本机真实凭证，内容未显示")
    if name in REVIEWED_BINARY and data.startswith(REVIEWED_BINARY[name]):
        return errors
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        return errors + [f"{name}: 未批准的二进制或非UTF-8内容"]
    if "\x00" in text:
        errors.append(f"{name}: 未批准的二进制内容")
    if re.search(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----", text):
        errors.append(f"{name}: 检出私钥正文，内容未显示")
    if re.search(r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,})\b", text):
        errors.append(f"{name}: 检出疑似API凭证，内容未显示")
    return errors


def git_blobs(root, treeish=None):
    """Read the staged snapshot or a committed tree, including deleted old files."""
    if treeish is None:
        raw = git(root, "ls-files", "--stage", "-z").stdout
        records = []
        for item in raw.split(b"\0"):
            if not item:
                continue
            metadata, name = item.split(b"\t", 1)
            mode, oid, stage = metadata.split()
            if stage != b"0":
                raise RuntimeError("暂存区存在未解决的合并冲突")
            records.append((mode.decode(), oid.decode(), name.decode("utf-8")))
    else:
        raw = git(root, "ls-tree", "-r", "-z", treeish).stdout
        records = []
        for item in raw.split(b"\0"):
            if not item:
                continue
            metadata, name = item.split(b"\t", 1)
            mode, kind, oid = metadata.split()
            if kind != b"blob":
                raise RuntimeError("交接包不允许未审阅的子模块")
            records.append((mode.decode(), oid.decode(), name.decode("utf-8")))
    return records


def audit(root=ROOT):
    secrets = local_secrets(root)
    errors, checked = [], set()
    names = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").stdout
    for value in names.split(b"\0"):
        if not value:
            continue
        name = value.decode("utf-8")
        if forbidden_name(name):
            errors.append(f"{name}: 禁止包含运行文件或敏感文件")
            continue
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
            errors.append(f"{name}: 路径不安全或不是普通文件")
            continue
        errors.extend(content_errors(name, path.read_bytes(), secrets))
        checked.add(name)
    objects = {}
    for mode, oid, name in git_blobs(root):
        if mode not in {"100644", "100755"}:
            errors.append(f"{name}: 不允许符号链接或子模块")
        objects.setdefault(oid, set()).add(name)
    commits = git(root, "rev-list", "--all").stdout.decode().splitlines()
    for commit in commits:
        for mode, oid, name in git_blobs(root, commit):
            if mode not in {"100644", "100755"}:
                errors.append(f"{name}: 历史中有未批准的文件类型")
            objects.setdefault(oid, set()).add(name)
    if objects:
        order = list(objects)
        raw = git(root, "cat-file", "--batch", input=("\n".join(order) + "\n").encode()).stdout
        offset = 0
        for oid in order:
            end = raw.index(b"\n", offset)
            header = raw[offset:end].split()
            if len(header) != 3 or header[1] != b"blob":
                raise RuntimeError("无法验证Git历史对象")
            size = int(header[2])
            content = raw[end + 1:end + 1 + size]
            offset = end + size + 2
            for name in objects[oid]:
                errors.extend(content_errors(name, content, secrets))
    if errors:
        raise ValueError("\n".join(sorted(set(errors))))
    return {"working_files": len(checked), "unique_git_blobs": len(objects), "commits": len(commits)}


def export(root=ROOT):
    result = audit(root)
    head = git(root, "rev-parse", "HEAD").stdout.decode().strip()
    branch = git(root, "branch", "--show-current").stdout.decode().strip()
    if not branch:
        raise RuntimeError("导出需要明确的任务分支")
    if git(root, "status", "--porcelain", "--untracked-files=all").stdout.strip():
        raise RuntimeError("工作目录尚未全部提交，停止导出以避免交接内容不一致")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = root / "outputs" / "git-handoff" / f"{stamp}-{head[:8]}"
    destination.mkdir(parents=True, exist_ok=False)
    bundle, archive = destination / "cooldatasim.bundle", destination / "cooldatasim-source.zip"
    git(root, "bundle", "create", str(bundle), "--all")
    git(root, "bundle", "verify", str(bundle))
    git(root, "archive", "--format=zip", "--prefix=cooldatasim/", "-o", str(archive), "HEAD")
    with zipfile.ZipFile(archive) as stream:
        names = stream.namelist()
        if any(forbidden_name(name.removeprefix("cooldatasim/")) for name in names if not name.endswith("/")):
            raise RuntimeError("源代码ZIP包含禁止文件")
    with tempfile.TemporaryDirectory(prefix="cooldatasim-git-verify-") as temporary:
        clone = Path(temporary) / "restored"
        git(root, "clone", "--no-hardlinks", "--branch", branch, str(bundle), str(clone))
        if git(clone, "rev-parse", "HEAD").stdout.decode().strip() != head:
            raise RuntimeError("离线克隆的提交基准不一致")
        for name in ("AGENTS.md", "README.md", "docs/ARCHITECTURE.md", "docs/RUNBOOK.md", ".env.example"):
            if not (clone / name).is_file():
                raise RuntimeError("离线克隆缺少项目入口")
        if (clone / ".env").exists():
            raise RuntimeError("离线克隆错误包含运行凭证")
    instructions = f"""cooldatasim Git源代码交接
分支：{branch}
提交：{head}

离线克隆：git clone -b {branch} cooldatasim.bundle cooldatasim
ZIP仅含源代码，不含.git历史。
先核对MANIFEST.json中的SHA-256，再读AGENTS.md、README.md、docs/HANDOFF.md和用户指定任务卡。
运行：python scripts/project.py install，然后python scripts/project.py check。
运行配置、密钥、数据库、客户/员工资料、模型权重和Docker镜像均不在此包中。
新机器按RUNBOOK生成自己的.env和数据库，不要从聊天或Git寻找真实凭证。
WhatsApp真机和AWS等未完成项以任务卡为准，源代码包不代表生产验收通过。
"""
    (destination / "交接说明.txt").write_text(instructions, encoding="utf-8", newline="\n")
    hashes = {}
    for path in sorted(destination.iterdir()):
        if path.is_file():
            with path.open("rb") as stream:
                hashes[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {"project": "cooldatasim", "branch": branch, "commit": head,
                "created_at_utc": stamp, "audit": result, "offline_clone_verified": True, "sha256": hashes}
    (destination / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit", "export"))
    command = parser.parse_args().command
    try:
        if command == "audit":
            print(json.dumps(audit(), ensure_ascii=False))
        else:
            print(export())
    except (OSError, ValueError, RuntimeError) as error:
        print("FAILED:", str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
