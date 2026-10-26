# Cool Data Sim 客服后台

GitHub目标仓库：`BOOMUN/cooldatasim`（私有开发仓库）。新接手先读 [项目交接入口](docs/HANDOFF.md)。

面向 Cool Data Sim 客服人員的專用後台，透過 WhatsApp Business 接待客戶，利用網站知識和可切換的對話模型提供回覆。使用者目前指定暫用 DeepSeek V4.1 Flash high，Qwen 對話設定保留。

**目前階段：本機首版已運行，專案整體仍在開發和聯調中。** 登入、客戶/會話、網站草稿採集、知識審核、商品資料及獨立向量/重排已接入；WhatsApp真機同步等項目仍未完成。應用狀態見TASK-003，向量接入證據見[TASK-004](docs/TASKS/TASK-004.md)，不把有限驗證當成整體驗收。

## 从哪里开始

1. 阅读 [AGENTS.md](AGENTS.md)。
2. 阅读 [需求基线](docs/REQUIREMENTS.md) 与 [架构](docs/ARCHITECTURE.md)。
3. 只执行用户指定的一张任务卡；本次仓库交接为 [TASK-005](docs/TASKS/TASK-005.md)，历史向量接入见TASK-004，整体业务待办仍见TASK-003。已结束的交接任务不自动授权新的业务修改。
4. 启动、环境和排错见 [RUNBOOK](docs/RUNBOOK.md)，关键选择见 [决策记录](docs/DECISIONS/README.md)。

## 当前可用命令

需要 Python 3.11+、Node.js 24 和 Git，容器运行还需要 Docker 的本机 Linux 引擎。以下命令适用于 PowerShell、Linux 和 macOS；均在仓库根目录执行。

```sh
python scripts/project.py install
python scripts/project.py test
python scripts/project.py lint
python scripts/project.py fmt
python scripts/project.py check
```

- `install`：创建隔离 .venv、安装 backend/requirements.lock，并执行前端 npm ci。
- `test`：治理工具单元测试及后端 pytest；测试使用隔离内存数据库和模型/通道模拟协议，不连接服务器或真实账号。
- `lint`：检查入口、任务边界、文档链接、文件格式、Python 语法、package JSON 及常见密钥误入库情况。
- `fmt`：规范管理文档、配置和 Python 文件的行尾及末尾空白；只处理本次治理文件。
- `check`：环境检查、lint、全部离线测试、Vue/TypeScript 类型检查和生产构建，是当前 CI 入口。

新增业务功能必须在同一任务补充对应验证。上述自动测试不等于外部 Qwen 推理或 WhatsApp 真机验收。

## 打开本机后台

地址：`http://127.0.0.1:8787/`。管理員帳號預設為 `admin`。`.env` 的 `COOLDATASIM_ADMIN_PASSWORD` 僅用於首次建立帳號；密碼另行變更後，以資料庫中的帳號密碼為準，不會在重啟時被初始化值覆蓋。不要把登入密碼寫入文件、截圖、PR 或日誌。

系統介面及使用者提示採繁體中文；來源原文與客戶訊息保持原樣。未配置、待審核與未聯調狀態都會明確顯示。

目前DeepSeek V4.1 Flash high、Qwen3-Embedding-0.6B及Qwen3-Reranker-0.6B已通過完整隔離流程。已發布知識可使用1024維向量、PostgreSQL相似度檢索及重排；目前網站資料仍為草稿，需人工審核發布。這不代表全站資料、真實WhatsApp或整體專案已驗收。

```sh
python scripts/app.py prepare
python scripts/app.py build
python scripts/app.py up
python scripts/app.py verify
```

prepare 只补齐缺失的本机应用凭证，不更改已有数据库密码。需要数据库镜像已构建，步骤见下方。API 和 Worker 使用同一个应用镜像，Compose 的 app profile 控制应用启动；默认数据库工具不会启动应用。

本機若存在私有`.env.vector-tunnel.json`，`app.py up`會確認或啟動雙跳SSH轉發。Windows重新開機後請執行一次up；宿主Python需Paramiko。私有設定與模型憑證不進Git或鏡像。

网站内容先进入草稿，人工核对后才发布；演练会话有明显标记且只限管理员。真实外发在 API 中硬性关闭。AI 未配置或不可用时返回明确错误，不伪造回复。

停止应用：`python scripts/app.py stop`（保留数据库）；打包应用与数据库镜像：`python scripts/app.py package`。包不含运行数据、凭证或模型权重，AWS 迁移仍未执行。

## 本机数据库

需要 Docker Desktop 的 Linux 容器引擎。初始化命令仅首次使用，已有 .env 时跳过；密码不在输出中显示。

```sh
python scripts/local_db.py init-env
python scripts/local_db.py build
python scripts/local_db.py up
python scripts/local_db.py verify
```

本机连接：`127.0.0.1:5433`，数据库 `cooldatasim`，应用账号 `cooldatasim_app`。密码和本机连接串仅保存在被忽略的 `.env` 中。容器内的应用未来应通过 Compose 服务名 `postgres:5432` 连接，不能照搬宿主机地址。

数据使用 `cooldatasim_postgres-data` 命名卷；初始化 SQL 只在新卷上运行。`stop` 保留数据；工具不提供删除卷命令。

```sh
python scripts/local_db.py status
python scripts/local_db.py backup
python scripts/local_db.py package
```

备份保存在 `outputs/backups/`，镜像包保存在 `outputs/releases/`；都不提交 Git。镜像包不含数据库数据、密钥或客服应用。迁移步骤见 RUNBOOK。

## 目录

```text
AGENTS.md                 AI 入口与权限边界
docs/REQUIREMENTS.md       已确认需求、提案和待确认项
docs/ARCHITECTURE.md       模块、数据流、模型分工
docs/RUNBOOK.md            当前检查命令、后续运行与排错约束
docs/TASKS/                当前任务、任务模板和后续工作队列
docs/DECISIONS/            决策及其状态
docs/AI_PROMPTS.md         固定任务提示词
scripts/project.py        可离线运行的治理工具
tests/test_repository.py  治理工具测试
backend/app/              FastAPI、权限、数据库、采集、LangGraph、通道
backend/tests/            业务接口和模块测试
frontend/                 Vue/TypeScript 页面与品牌样式
scripts/app.py            应用镜像构建、启动、验证与打包
scripts/local_db.py       本机数据库部署、验证、备份与镜像导出
compose.yaml              独立数据库服务，端口仅对本机开放
infra/postgres/           固定来源镜像与初始化 SQL
.github/                  CI 与 PR 模板
.env.example              规划中的环境变量，无真实凭证
```

`.inspect-relaydesk/` 是本地参考克隆，已忽略，不应作为子模块或本项目代码提交。参考基准为 `BOOMUN/relaydesk@a904a8e27e74e3e34e83d232fba257565b27caa4`；使用其代码前应核对授权与许可证，并记录移入范围。

## Git 与交付

一个任务一个 `ai/TASK-NNN` 分支。禁止直接修改或推送 `main` / `master`，禁止强推。TASK-005已获明确授权创建私有仓库、提交并推送ai/TASK-005和创建PR，具体结果见任务卡；AWS部署仍未执行。

配置远端后，通过 PR 人工 Review 再合并；在托管平台设置主分支保护及必需 CI。本地文件不能代替远端保护规则。发布、打标签、删除分支均需对应任务授权。

离线Git交接：`python scripts/package_git.py audit` 执行凭证及历史审计；提交后运行 `python scripts/package_git.py export` 生成bundle、纯源代码ZIP、SHA-256清单和恢复说明。此命令排除运行数据、凭证和本机依赖。
