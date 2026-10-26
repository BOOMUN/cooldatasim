# 决策索引

状态约定：已接受＝用户已明确；保留待验证＝方案暂留，能力未保证；提议＝尚待确认。ADR 状态不代表部署授权。

| 编号 | 决策 | 状态 |
| --- | --- | --- |
| [ADR-001](ADR-001-model-boundaries.md) | Qwen 模型分工与数据隔离 | 目标已接受，实现方案待设计 |
| [ADR-002](ADR-002-whatsapp-channel.md) | Evolution 扫码接入 | 保留待验证 |
| [ADR-003](ADR-003-stack.md) | 新后台技术栈 | 已实施首版；Redis/SSE 未采用 |
| [ADR-004](ADR-004-local-containers.md) | 本机容器部署，后迁移 AWS | 已接受；数据库基础先落地 |
| [ADR-005](ADR-005-initial-app.md) | 首版流程与验收边界 | 本机实施，外部联调待完成 |
| [ADR-006](ADR-006-vector-service.md) | 獨立CPU向量與重排接口 | 已實際接入並通過隔離鏈路驗證 |

重要变更新增 ADR 或注明替代关系，并同步需求和任务。记录背景、决策、后果，不只写结论。
