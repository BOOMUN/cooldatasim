# ADR-003：参考 RelayDesk 的技术栈

- 日期：2026-10-24
- 状态：TASK-003 已授权实施；具体初版收敛见 ADR-005。

## 背景

用户要求重新开发专用后台，RelayDesk 仅作为 GitHub 参考。新项目尚无应用代码，不存在已运行的前后端或数据库。

## 决策提案

已采用前端 Vue 3 + TypeScript + Vite、后端 Python + FastAPI、业务数据 PostgreSQL、知识索引 pgvector、LangGraph 流程编排。依赖锁定在前后端 lock 文件。首版队列使用 PostgreSQL Job + Worker；Redis 与 SSE 尚未采用，不能计为已实现。

## 后果

技术结构可参考既有源码，但不能复制其凭证、数据、默认业务规则或宣称全部功能可用。首次加入业务代码时必须补充依赖锁定、真实启动命令、业务测试和迁移／回滚流程。当前 stdlib 检查脚本只覆盖治理基础。
