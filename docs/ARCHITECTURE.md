# 系统架构

## 当前与目标

当前仓库已具备本机应用、API、Worker 和 PostgreSQL/pgvector。目标模块已开始实现，外部联调和完整功能仍未完成。初版边界见 [ADR-005](DECISIONS/ADR-005-initial-app.md)，部署方向见 [ADR-004](DECISIONS/ADR-004-local-containers.md)。

```text
客服浏览器
  └─ Cool Data Sim 后端
       ├─ 会话、客户、客服分配、内部备注
       ├─ Evolution 通道 ─ WhatsApp Business
       ├─ 网站采集 Worker ─ Cool Data Sim 网站
       ├─ 商品结构化数据 + 独立已发布知识索引
       └─ AI 编排
            ├─ Qwen Embedding：向量检索
            ├─ Qwen Reranker：候选排序
            └─ 對話模型：目前 DeepSeek V4.1 Flash high，Qwen 保留
```

## 模块与数据边界

| 模块 | 输入 | 输出及约束 |
| --- | --- | --- |
| 通道适配 | Webhook、客服发送请求 | 统一消息 ID、回执、去重，保持手机发出消息的方向 |
| 聊天工作台 | 会话和客户状态 | 人工回复、接管、备注；备注不得外发 |
| 网站采集 | 允许的网址 | 正文、来源、时间、内容指纹；网页文本不是系统指令 |
| 商品资料 | 商品页及可靠字段 | 价格、币种、规格、链接、有效性；不通过语言模型猜报价 |
| 知识管理 | 抓取文档与编辑 | 版本、审核和发布状态；具体 UI 在任务中细化 |
| 检索服务 | 问题、筛选条件 | 本项目已发布证据；禁止串入员工知识 |
| 对话生成 | 当前会话与检索证据 | 可追溯回复；无资料追问或转人工 |
| 发送控制 | 回复、会话模式 | 接管后取消未发 AI 回复；重复请求不重复发出 |

## 核心流程

1. 网站采集 → 提取与去重 → 审核 → 商品入库／文档分块与向量化 → 发布。
2. 客户问题 → 判断缺失条件 → 商品精确查询／知识检索 → 重排 → Qwen 对话生成 → 校验依据 → 自动发送或客服确认。
3. 手机或后台发出消息 → 统一消息记录 → 回执更新；不得误当新客户问题触发 AI。

## 模型边界

Qwen對話模型的設定服務名曾讀取為`qwen3.8-27b`，目前保留設定。對話使用OpenCode的`deepseek-v4.1-flash`、`reasoning_effort=high`。Embedding為`Qwen3-Embedding-0.6B`、1024維；重排為`Qwen3-Reranker-0.6B`，已透過TASK-004獨立CPU服務接入本後台。

既有員工RAG服務維持自身業務。新`cooldatasim-vector-api.service`只唯讀載入模型檔，提供Bearer驗證的模型接口，不讀知識文件、不保存輸入、不匯入員工程式。文件向量和查詢向量使用不同input_type；查詢/重排使用本專案指令。

模型電腦loopback8195經既有SSH跳板和固定主機公鑰的第二跳，到本機loopback18082；Docker使用host.docker.internal連接。沒有新增AWS公開端口。服務使用8個CPU執行緒、8GB記憶體上限，未使用GPU。

浏览器不持有模型或 WhatsApp 凭证；后端通过经授权的私有网络或隧道访问推理服务。应用先部署本机，后续以镜像迁 AWS；模型电脑保持独立，模型网络方案尚未落实。

数据库由本机 Compose 项目 cooldatasim 管理，使用 PostgreSQL 17、pgvector、独立 app schema 和普通应用账号。开发连接仅为本机 127.0.0.1:5433，应用为 127.0.0.1:8787。初始业务表和 schema_version=1 已建立；后续 schema 变更需要显式迁移，不可依赖 create_all 自动升级。

## 已落地模块

- backend/app/main.py：HTTP 接口、Cookie 会话与 CSRF、角色检查、客户会话、草稿审核与模型/通道状态。
- knowledge.py / worker.py：持久采集任务、安全公开 URL、HTML/JSON-LD、审核快照和向量索引适配。
- ai.py：真实 LangGraph 的 retrieve → generate → validate 节点。明确区别 keyword 与 hybrid 检索，不向量化时不制造索引。
- channels.py：受控 Evolution 协议适配，手机消息方向、去重和回执处理已有模拟测试；未关联真实号码。
- frontend/src：真实 API 驱动的工作台，空数据与未配置状态显式显示，无伪造客户/模型答案。

采集 Job 使用数据库锁领取，过期运行任务标失败并供人工重试；自动计划调度、完整重试策略和 Redis 尚未实现。会话上下文来自数据库，LangGraph 单次建议流程未实现跨任务 checkpoint 恢复。

## 同步可靠性待实现要求

- 消息 ID 幂等、重复回调合并、乱序回执处理、断线补拉及媒体失败重试。
- 后台客服未读与客户已读回执分别记录。
- 人工接管检查在最终发送前执行，不能仅在生成开始时判断。
- 模型超时或 503 不应造成假回复或重复发送。
- 向量记录模型身份、维度、分块版本；换模型时重建对应索引，不混用。

接口基准见 [API.md](API.md)。并发与容量门槛、生产审计、全量历史分页、SSE、自动回复和真实媒体流仍需后续实现和验收。
