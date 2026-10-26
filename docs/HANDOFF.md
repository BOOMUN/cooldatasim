# cooldatasim 项目交接入口

交接日期：2026-10-26（Asia/Shanghai）。这是可审阅的开发版本，整体客服系统尚未通过完整生产验收。

## AI 开始工作

按顺序读 AGENTS.md、README.md、ARCHITECTURE.md、REQUIREMENTS.md，再读用户指定的一张任务卡。不要把历史任务的授权自动扩大到新任务，不要一次执行整个待办队列。

任务索引见 [TASKS/README.md](TASKS/README.md)，固定提示词见 [AI_PROMPTS.md](AI_PROMPTS.md)。任务卡完成后必须更新实际验证结果；旧记录保留日期，不能冒充当前服务状态。

## 目前有什么

| 范围 | 已实现或验证的内容 | 仍需完成 |
| --- | --- | --- |
| 本机后台 | Vue/TypeScript、FastAPI、登录、角色、客户、会话、内部备注、本地演练 | 生产权限/负载验收、完整历史分页、SSE、导入导出等 |
| 网站资料 | 公开HTML/JSON-LD采集、草稿、商品识别、发布快照及撤回 | 全站覆盖、人工内容审核、PDF/图片/动态页面、计划同步、价格历史 |
| 对话模型 | 2026-10-24已验证DeepSeek V4.1 Flash high，来源与价格约束 | 当前服务可用性需按授权重新检查，Qwen对话备用设置未验证可用 |
| 向量/重排 | 2026-10-24已验证独立CPU接口、1024维、真实入库/混合检索/重排 | 真实网站发布后的业务问答、长时间稳定性和容量验收 |
| WhatsApp | Evolution受控协议适配，消息方向/去重/回执有隔离测试 | 真实配对、媒体、引用/回应、编辑撤回、历史补拉、群聊/通话和真实外发 |
| 部署 | 本机Docker、独立PostgreSQL/pgvector、镜像打包命令 | AWS实机迁移、私网模型连接、TLS和完整恢复验收 |

真实网站资料曾有10份草稿、8项商品，有限采集仍有未覆盖页面。这些是历史记录，Git不包含运行数据库，也不包含已审核知识数据。

## 新机器验证与运行

要求 Python 3.11+、Node.js 24、Git。安装和离线检查：

```sh
python scripts/project.py install
python scripts/project.py check
```

check覆盖治理工具测试、后端与模型接口模拟测试、前端回归测试、类型检查及构建。它不会连接模型电脑、AWS、真实数据库或WhatsApp，不能据此宣称外部联调通过。

首次本机运行另需 Docker Linux 引擎：

```sh
python scripts/local_db.py init-env
python scripts/local_db.py build
python scripts/local_db.py up
python scripts/app.py prepare
python scripts/app.py build
python scripts/app.py up
python scripts/app.py verify
```

新建.env会生成新随机凭证；已有.env不覆盖。管理员初始密码仅用于首次建号，后续密码保存在数据库。Git不携带原机器的账号密码、模型API Key、SSH配置或知识数据。

外部对话、向量和通道由新机器在本地.env配置。模型电脑的部署资料见 [RUNBOOK.md](RUNBOOK.md) 与 [ADR-006](DECISIONS/ADR-006-vector-service.md)，没有授权时不要自动连线、安装、切换或重启服务。

## 评审与恢复

- 一个任务一个ai/TASK-NNN分支，通过PR审阅后由人工合并。初次交接代码在ai/TASK-005，main由GitHub初始化README，尚未合并的PR是完整源代码入口。
- 依赖、权限、迁移、外发通道和远端服务改动标为重点Review；源代码初始导入不是回溯伪造历史开发提交。
- 主分支保护是否实际启用，以GitHub仓库设置和TASK-005记录为准；不能只靠文档声称已保护。
- 当前GitHub API要求账号升级Pro或改为公开仓库才能启用私有仓库分支保护，故远端保护尚未启用。install会在未自定义hooks的仓库启用本地pre-push保护，拒绝直推main/master和非快进改写；它可以被用户绕过，不能作为远端强制保护的替代证明。
- 离线bundle可用 `git clone -b ai/TASK-005 cooldatasim.bundle cooldatasim` 恢复。ZIP是纯源代码，不含.git历史。
- bundle、ZIP、校验清单由 `python scripts/package_git.py export` 产生，位于被忽略的outputs/git-handoff。导出会审计当前文件、暂存区和全部Git历史；不要手工把工作目录整包压缩。
- Git文件、Docker镜像、数据库备份和环境密钥是不同交付物，不能互相替代。
