# TASK-002：本机独立数据库与容器迁移基础

## 状态

本机独立数据库已部署并验证，待人工验收。用户已指定先在当前 Windows 本机部署，后续以镜像包迁移 AWS。本轮只落实 PostgreSQL + pgvector 数据库，不扩展客服业务。

## 背景

本机 Docker Desktop 的 Linux/amd64 引擎可用；已有其他项目容器及数据卷，不能复用或改动。TASK-001 的本地治理文件尚未提交，本任务在 ai/TASK-002 分支保留其内容，不自动 commit 或推送。

## 验收标准

- 独立 cooldatasim Compose 项目、数据库、账号和命名卷，仅绑定本机 127.0.0.1:5433。
- 固定 PostgreSQL 17 / pgvector 上游镜像 digest，初始化向量扩展与普通应用账号。
- 随机凭证只写入 Git 忽略的本地 .env；已有 .env 不覆盖，不打印密码。
- 验证服务健康、密码认证、错误密码拒绝和 1024 维向量写入／检索。
- 检查命名卷和本地端口绑定；提供数据库备份及镜像导出命令。
- 镜像包与数据库数据、环境密钥分离；AWS 本轮不操作。
- 治理检查和新脚本测试通过，未验证项明确。

## 允许修改

- `README.md`
- `AGENTS.md`
- `.env.example`
- `docs/REQUIREMENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/RUNBOOK.md`
- `docs/TASKS/README.md`
- `docs/TASKS/TASK-002.md`
- `docs/DECISIONS/README.md`
- `docs/DECISIONS/ADR-004-local-containers.md`
- `scripts/project.py`
- `scripts/local_db.py`
- `tests/test_repository.py`
- `tests/test_local_db.py`
- `compose.yaml`
- `infra/postgres/Dockerfile`
- `infra/postgres/001-init.sql`

本地运行产物 `.env`、`outputs/` 由已有 .gitignore 排除，不纳入版本库。

## 禁止修改

TASK-001 历史验收记录、参考克隆、Logo、其他项目容器／卷／账号、AWS、现有模型电脑、WhatsApp 实例。禁止清空卷、prune、修改远端、真实外发消息或复制凭证进镜像。

## 操作权限

允许新建任务分支、上述文件、拉取和构建数据库镜像、启动本项目本机数据库、初始化本项目数据库角色、运行隔离测试、输出本地备份和镜像包。仅允许控制本任务创建的 Compose 资源。禁止 commit/push/tag、AWS 部署或切换远端模型。

## 执行计划

1. 检查 Docker、端口和既有资源，固定镜像来源。
2. 编写独立数据库 Compose、初始化及维护脚本，更新当前事实和部署决策。
3. 运行本地脚本测试，再部署数据库并验证认证和向量功能。
4. 验证备份与迁移包，记录结果和未覆盖项。

## 验证命令

```sh
python scripts/project.py check
python scripts/local_db.py init-env
python scripts/local_db.py build
python scripts/local_db.py up
python scripts/local_db.py verify
python scripts/local_db.py backup
python scripts/local_db.py package
```

## 验证结果

验证日期：2026-10-24（Asia/Shanghai），Windows 本机 Docker Desktop，linux/amd64。

- `python scripts/project.py check`：通过；26 个管理文件检查、27 项离线测试。覆盖新增随机凭证、不覆盖环境、端口校验、打包白名单、Docker 失败脱敏、拒绝远程 Docker host/context/named pipe 等路径。
- `init-env`、`build`、`up`：成功，本机独立容器 cooldatasim-postgres-1 保持运行。
- 数据库实测：PostgreSQL 17.11、pgvector 0.8.7，数据库 cooldatasim，普通账号 cooldatasim_app 无超级用户／建库／建角色权限。
- `verify`：健康检查通过；正确密码 TCP 认证成功、错误密码被拒绝；vector(1024) 插入和相似度查询通过，测试事务回滚。
- 端口与卷：仅 127.0.0.1:5433，Windows 宿主机 TCP 可达；使用 cooldatasim_postgres-data 命名卷。
- 持久性实测：仅在本项目 app schema 创建随机测试表，强制重建本项目容器后仍读到测试标记；测试表已清理。
- 备份：outputs/backups/20261024T060246Z-e9b421/cooldatasim.dump，pg_restore --list 通过；另恢复到随机隔离测试数据库并确认 vector 扩展及 app schema，测试库已删除。
- 最新迁移包：outputs/releases/20261024T060420Z-34cbb9，约 153.2 MiB；所有文件 SHA-256 校验通过，docker image load 后镜像 ID 与清单一致。
- 迁移包只含数据库镜像和启动资料，未包含 .env、数据库备份、模型权重或业务应用。

未执行：AWS 实机迁移、ARM 平台、实际业务表与数据恢复、客服应用、网站知识采集、Qwen 对话和 WhatsApp 联调。此次恢复测试基于当前数据库基础结构，不代表未来业务数据已验收。

## 人工验收与风险

数据库初始化和权限设置是人工重点 Review 项。PostgreSQL 主版本变化需单独迁移；镜像不含数据卷。未来 AWS 使用匹配的 linux/amd64 平台，并重新配置凭证和私有模型连通性。本轮不发布数据库到公网。
