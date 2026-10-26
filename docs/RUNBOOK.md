# 运行与排错手册

## 当前可运行内容

本机首版已有 API、前端和 Worker。不要运行参考仓库并宣称它是本项目。`.env.example` 为当前配置契约；模型和通道即使有配置入口也不代表已连通。

从根目录执行：

```sh
python scripts/project.py install
python scripts/project.py check
```

若出现格式问题，执行 `python scripts/project.py fmt` 后重新检查。Python 需要 3.11+，Git 需在 PATH 中。Windows 可在确认版本后使用 `py -3` 替代 `python`。

`install` 安装隔离 Python 与 npm 依赖。`test` 包括治理和后端隔离测试，`check` 另运行前端回归测试及生产构建；这些验证不连接真实模型或 WhatsApp。`fmt` 会写入管理和部署文件。真实运行验证用 app/local_db 工具。

## 本机客服应用

```sh
python scripts/project.py install
python scripts/app.py prepare
python scripts/app.py build
python scripts/app.py up
python scripts/app.py verify
```

地址 http://127.0.0.1:8787/。預設帳號 admin，首次建立帳號使用本機 .env 的 COOLDATASIM_ADMIN_PASSWORD；之後變更密碼以資料庫為準，初始化變數不代表目前密碼。資料庫首次啟動步驟見下節。應用啟動僅執行初始增量建表和管理員初始化，不刪除表、不重設現有帳號密碼；修改 .env 不能重設資料庫中已有密碼。

app profile 包括 API 与独立 Worker。只有 admin 能创建演练会话，演练消息不出本机。真实外发在路由中关闭，设置环境开关也不会绕过首版限制。

网站采集默认每批最多 10 页，达到上限时仍有未采集页面；“本批次完成”不是“全站完成”。页面和商品均进入待审核；没有自动发布。测试报告必须分别记录抓取、正文质量、审核、向量化与模型回答。

文档编辑后旧发布快照继续生效，撤回会删除索引并取消生效快照。未配置 Embedding 时发布会明确标记 text_only；这不是向量检索通过。Qwen、向量和重排采用独立配置；未配置时有明确错误，不会偷偷改用别的模型。

首版 SQLAlchemy create_all 仅用于 schema_version=1；后续表结构变化必须增加显式迁移、备份和回滚步骤，不能自动删除重建数据库。

停止 API/Worker 用 `python scripts/app.py stop`。导出应用+数据库镜像用 `python scripts/app.py package`，输出到 outputs/app-releases，迁移包不含 .env、数据库内容或模型权重。

## 對話模型與向量設定

- `COOLDATASIM_CHAT_PROVIDER/BASE_URL/MODEL/API_KEY/REASONING_EFFORT` 是目前對話設定；整組未設定才回退 `QWEN_*`，不交叉使用兩組憑證。
- OpenCode Go 的模型識別為 `deepseek-v4.1-flash`，使用 high、thinking enabled、JSON回覆及穩定的 `x-opencode-session`。部署命名空間由本機產生，原始登入Token不外傳。官方依據：[模型與接口](https://opencode.ai/v2/docs/console/go/)、[會話識別](https://opencode.ai/v2/docs/console/harnesses/)、[DeepSeek推理參數](https://api-docs.deepseek.com/guides/thinking_mode/)。
- API Key 只保存在被忽略的 `.env`，不得複製至文件或映像。使用者提供的憑證檔只作設定資料，不作執行指令。
- 更新設定後需重新建立 API/Worker 容器；模型清單可達、實際推理、檢索正確性分別驗證。
- TASK-004已部署獨立CPU服務，提供`/v1/models`、`/v1/embeddings`與`/v1/rerank`。它不讀員工文件、不保存輸入、不使用GPU；員工知識服務維持原樣。
- 本機 Qwen SSH 轉發工具為 `scripts/model_tunnel.py`（宿主 Python 需 Paramiko 5.0.0）；私有連線設定在 `.env.qwen-tunnel.json`。只監聽 loopback 並校驗已知SSH主機金鑰。使用 DeepSeek 時轉發程序已停止，沒有切換模型電腦上的 H3/Qwen 服務。

## 獨立向量服務與轉發維護

- 服務名稱cooldatasim-vector-api.service，目錄為模型電腦`/home/ubuntu/ai/workspace/cooldatasim-vector-api`，僅監聽127.0.0.1:8195，8個Torch執行緒、8GB記憶體上限。
- 本機雙跳轉發為`python scripts/vector_tunnel.py`，僅監聽127.0.0.1:18082。私有設定在.env.vector-tunnel.json，包含密鑰路徑及已固定的模型主機公鑰，不含密鑰正文。
- 啟動應用`python scripts/app.py up`會在私有設定存在時確認或啟動轉發。Windows重新開機後需執行up；Docker容器自行重啟不會啟動宿主Python程式，未新增系統排程。
- 模型服務已啟用user systemd啟動。查狀態用`python scripts/deploy_vectors.py status`；更新程式用deploy（僅限該任務再次獲授權的範圍），不修改員工或GPU服務。
- 獨立憑證保存在遠端專案目錄的.env及本機.env；不要印出完整Docker環境、服務環境或私有設定。
- 文件嵌入使用input_type=document，查詢使用query；固定1024維。超出2048Token明確拒絕，忙碌時429；不是自動靜默截斷或偽造向量。
- 已審核發布文件才生成向量。撤回會移除該文件索引。當前網站10份文檔仍待審核；模型接通不會自動發布它們。
- 重排分數是排序依據，不代表答案正確率。應用測試結果與完整網站業務品質分開驗收。
- 新服務只復用既有Torch/Transformers環境與模型檔，沒有修改原有Python依賴；未來變更共享環境需同步Review兩個服務。

## 本機資料庫部署與維護

1. 确认 Docker Desktop 已启动，使用 Linux 容器，端口 5433 空闲。
2. 首次执行 `python scripts/local_db.py init-env`；只在 .env 不存在时生成，管理员及应用密码各自随机。
3. 执行 `python scripts/local_db.py build` 构建固定来源的数据库镜像。
4. 执行 `python scripts/local_db.py up`，等待健康检查。
5. 执行 `python scripts/local_db.py verify`，验证密码、1024 维向量、应用权限、本机监听和命名卷。
6. `python scripts/local_db.py stop` 只停止本项目数据库，保留数据卷；启动使用 up。

初始化 SQL 仅在空卷首次启动执行。不要删除卷来解决密码或升级问题；已有卷的密码不会因编辑 .env 自动改变。更改密码应通过独立任务同步修改数据库与环境配置。

脚本不打印完整 Docker 配置或环境，所有 Docker 操作只接受本机 Unix socket 或 Windows 本地 named pipe，拒绝远程 Docker context。故障时先运行 status，使用脱敏日志排错。端口冲突、未知同名资源或已有 .env 会明确失败，不覆盖其他项目。命名卷为 cooldatasim_postgres-data，数据库为 cooldatasim，普通应用角色为 cooldatasim_app。

## 镜像、数据和 AWS 迁移

- `python scripts/local_db.py backup`：生成 pg_dump 自定义格式归档，并用 pg_restore --list 检查结构。归档位于 outputs/backups，可能含敏感数据，不进入镜像包或 Git。
- `python scripts/local_db.py package`：输出数据库镜像 tar、Compose、维护脚本、空凭证示例、迁移说明和 SHA-256 清单。位于 outputs/releases，不含 .env、数据库卷或模型权重。
- 镜像为 linux/amd64，目标 AWS 应选择 x86_64；ARM 需单独构建与验证。
- AWS 执行前核对 SHA-256 清单，docker image load 导入镜像，再用 init-env 生成新凭证，使用 up 和 verify。迁移包中的脚本无需构建上下文即可启动已导入镜像。
- 完整数据迁移另建任务：传输受控备份、恢复数据库、转移附件、核对记录数量及向量版本，并验证 Qwen 私有网络与通道回调。
- 镜像加载成功不代表数据迁移成功。不要将开发环境密码照搬 AWS，不对公网开放 5432/5433。

依据：[Docker image save](https://docs.docker.com/reference/cli/docker/image/save/)、[Docker volumes](https://docs.docker.com/engine/storage/volumes/)、[pgvector](https://github.com/pgvector/pgvector)。

## Git 工作流程

```sh
git status --short --branch
git switch -c ai/TASK-003
# 已在对应分支时不重复创建
python scripts/project.py check
git diff --check
git diff --stat
git status --short
```

新建且尚未跟踪的文件不会出现在普通 `git diff` 中，必须结合 `git status` 和文件内容检查。当前仓库创建治理任务前无提交，原始分支名为 master；不能假定远端 main 已存在。

提交、推送、PR、合并和 tag 按具体任务授权执行。不要使用 `git add .` 无筛选纳入参考克隆、生成物或凭证。PR 应只包含任务卡允许的文件。主分支保护需由有权限者在远端启用，当前未配置远端，不能标记为已启用。

## 历史环境观察：2026-10-24，非实时状态

- SSH 曾成功登录模型机器，检查连接已关闭。
- 现有员工 RAG 的健康接口曾报告 CPU、1024 维、Embedding 与 Reranker ready。
- Qwen 入口 `/v1/models` 曾返回 503，上游本机端口 18000 连接被拒绝。
- 当时 ComfyUI 占用约 86 GiB 显存；不能推断现在仍然相同。
- 本项目没有部署在该服务器，服务器也没有因此被改动。

本文不保存服务器公网地址、登录命令、密钥路径或凭证。重新检查需要从用户授权的安全渠道取得连接信息。

## 后续 Qwen 只读检查步骤

1. 确认当前任务允许连接检查，取得安全存放的凭证。
2. 查询进程、监听端口、模型网关 `/v1/models` 与上游状态，日志仅截取必要且脱敏的部分。
3. 只有模型可用且获测试授权时，发送不含客户资料的最小对话请求。
4. 记录时间、HTTP 状态、模型服务名与响应耗时，分清网关可达和模型可生成。
5. 遇到 503 或未监听就报告阻碍；不擅自停 ComfyUI、切换 GPU 模型、重启服务或改配置。

## 未来部署与业务验收

本机数据库和应用具备上述命令；完整生产上线、实际业务数据迁移、Qwen 推理与 WhatsApp 联调仍未完成。迁移、依赖升级、权限与通道变更要有人工重点 Review。

WhatsApp 联调使用指定测试号码和隔离数据，明确哪些步骤实际发送消息。知识发布及删除仅在授权环境执行。测试报告需记录环境与版本，代码静态检查不能代替真机测试。

## 迭代维护

- 每个迭代核对 README、AGENTS、架构和当前任务是否一致。
- 决策发生变化时新增或替代 ADR，不悄悄修改“保留方案”为“已验证”。
- 依赖和业务代码加入后更新 CI；保持单一 `check` 入口覆盖实际要求。
- 清理已合并分支和发布 tag 仅在用户授权后进行；不在本次治理任务执行。
