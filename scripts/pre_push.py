"""Local guard: reject direct protected-branch pushes and history rewrites."""

import subprocess
import sys


def check_updates(lines, run=subprocess.run):
    for line in lines:
        fields = line.split()
        if len(fields) != 4:
            return "推送元数据不完整，已停止"
        local_ref, local_oid, remote_ref, remote_oid = fields
        if remote_ref in {"refs/heads/main", "refs/heads/master"}:
            return "禁止直接推送或删除main/master，请通过任务分支和PR人工审核"
        local_zero = local_oid and set(local_oid) == {"0"}
        remote_zero = remote_oid and set(remote_oid) == {"0"}
        if local_zero or remote_zero or local_oid == remote_oid:
            continue
        if remote_ref.startswith("refs/tags/"):
            return "禁止改写已有版本标签"
        result = run(["git", "merge-base", "--is-ancestor", remote_oid, local_oid],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode:
            return "禁止强推或无法确认历史关系，请先fetch并保留远端历史"
    return None


def main():
    error = check_updates(sys.stdin.read().splitlines())
    if error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
