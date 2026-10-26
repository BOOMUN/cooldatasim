# TASK-001：建立可审阅、可验证的仓库治理基础

## 状态

本地治理完成，待人工验收；仅本地治理文件已授权。尚未提交、推送或创建 PR。

## 背景

用户要求仓库自带入口、任务边界、验证命令、决策记录和 PR/CI。根目录原本没有提交或业务源码，仅有本地 RelayDesk 参考克隆及 Logo 资料。本任务不实现客服业务。

## 验收标准

- README、AGENTS、架构、运维、需求、任务和决策可相互定位。
- 已确认需求、拟议选型、参考实现、历史检查结果明确分开。
- 单任务分支为 `ai/TASK-001`；不在 master/main 上工作。
- 安装环境检查、测试、lint、格式规范及总检查命令实际可运行。
- CI 配置在 Linux 与 Windows 调用相同入口；PR 模板列出验证与权限 Review。
- 真实密钥和参考克隆不进入仓库；新建 `.env.example` 不含实际连接凭证。
- 业务代码、服务器和外部系统没有因本任务被修改。

## 允许修改

- `README.md`
- `AGENTS.md`
- `.gitignore`
- `.env.example`
- `docs/REQUIREMENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/RUNBOOK.md`
- `docs/AI_PROMPTS.md`
- `docs/TASKS/README.md`
- `docs/TASKS/_TEMPLATE.md`
- `docs/TASKS/TASK-001.md`
- `docs/DECISIONS/README.md`
- `docs/DECISIONS/ADR-001-model-boundaries.md`
- `docs/DECISIONS/ADR-002-whatsapp-channel.md`
- `docs/DECISIONS/ADR-003-stack.md`
- `scripts/project.py`
- `tests/test_repository.py`
- `.github/workflows/ci.yml`
- `.github/pull_request_template.md`

## 禁止修改

`.inspect-relaydesk/`、已有 Logo、业务源码、服务器、密钥及其他任务外文件。

## 操作权限

允许创建本地任务分支、上述治理文件及运行本地检查。禁止连接或修改服务器、安装业务依赖、发 WhatsApp 消息、发布知识、commit/push/tag、创建远端仓库或 PR。

## 执行计划

1. 核对根目录、Git 状态、上级 AGENTS 和参考基准。
2. 在任务分支写入事实、规则、需求和决策。
3. 建立不依赖外部包的检查脚本、测试和 CI。
4. 验证正常与失败路径，检查文件范围和敏感内容，记录结果。

## 验证命令

```sh
python scripts/project.py install
python scripts/project.py fmt
python scripts/project.py lint
python scripts/project.py test
python scripts/project.py check
git diff --check
git status --short --branch
```

## 验证结果

验证日期：2026-10-24（Asia/Shanghai）。执行环境：Windows，Python 3.14.7。

- `python scripts/project.py fmt`：通过，0 个文件需要格式调整。
- `python scripts/project.py check`：通过；包含 Python/Git 环境检查、19 个治理文件 lint、15 项测试。
- 测试覆盖：文档缺失／断链、任务范围缺失或超出、私钥与 API Token 检测且不回显、环境示例空凭证、敏感文件名、路径逃逸、格式化幂等和 Python 字符串保护、语法错误、Git 枚举失败、额外未跟踪文件扫描。
- CI YAML：使用本机已有 PyYAML 单独解析通过，并核对 PR/push/manual 触发、两种操作系统矩阵、只读权限与 check 命令。PyYAML 不是本项目脚本依赖。
- `git diff --check`：通过；本次均为未跟踪新文件，格式内容主要由治理 lint 检查。
- Git 忽略规则：参考克隆、Logo、本地环境文件及密钥文件被忽略；`.env.example` 保留为可提交文件。
- 当前分支：`ai/TASK-001`；没有远端，没有提交记录。

未执行：Linux 本机检查、GitHub 托管 CI、应用启动、业务测试、WhatsApp 联调、Qwen 对话、部署及分支保护配置。当前结果不代表这些项目通过。

## 人工验收与风险

- 审阅所有新文件；无提交基准时普通 git diff 不能显示未跟踪文件内容。
- 没有远端，PR、分支保护、远端 CI 均尚未启用或运行。
- 文档记录的 Qwen 503 是此前观察，本任务不重新连接或恢复服务。
- 建议提交信息：`chore: 建立 Cool Data Sim 仓库治理与验证基础`。仅作为建议，不自动提交。
