# 首版接口契约（TASK-003）

本文件为当前实现契约，不表示全部接口已验证。统一前缀 `/api`，JSON，异常 `{detail: string}`。通过 HttpOnly 会话 cookie 登录，写请求使用 `X-CSRF-Token`（登录除外）。时间为 ISO UTC。

## 登录与基础

- POST `/auth/login` `{username,password}` → `{user:{id,username,display_name,role},csrf_token}`。
- GET `/auth/me` → 同上；POST `/auth/logout`。
- GET `/health` → 无凭证基础健康；GET `/status` → 登录后运行状态。
- GET `/users` → 可分配客服简表。

## 客户、会话与消息

- GET `/contacts?q=` → `Contact[]`；POST `/contacts` `{display_name,phone,tags?,notes?,attributes?}`。
- PATCH `/contacts/{id}` 同可编辑字段；Contact 含 id/display_name/phone/tags/notes/attributes/language。
- GET `/conversations?q=&view=all|mine|unassigned|unread` → `Conversation[]`。
- POST `/conversations` `{contact_id}` → Conversation；GET `/conversations/{id}` → `{...Conversation,messages:Message[]}`。
- PATCH `/conversations/{id}` `{mode?:manual|ai_draft,assigned_user_id?:number|null}`。
- Conversation 含 id/contact/mode/status/unread_count/assigned_user_id/updated_at/sandbox/preview。
- Message 含 id/body/kind/direction/sender_type/status/created_at/metadata；direction=incoming|outgoing|internal。
- POST `/conversations/{id}/messages` `{body,internal,idempotency_key}`；真实外发默认禁用返回409，内部备注和 sandbox 消息可用。
- POST `/conversations/{id}/read`；POST `/conversations/{id}/suggest` → AIResult。
- POST `/sandbox` → 新建明确标记的本地演练会话；POST `/conversations/{id}/simulate` `{body}` 只用于 sandbox。

## 知识与商品

- GET `/sources` → Source[]；POST `/sources` `{name,url,max_pages?:number}`。
- POST `/sources/{id}/sync` → Job；GET `/jobs` → Job[]。
- GET `/documents?q=&status=` → Document[]；POST `/documents` `{title,url?,category?,content}`（手工草稿）。
- GET `/documents/{id}` → Document；PATCH 同可编辑字段；POST `/documents/{id}/publish`；POST `/documents/{id}/withdraw`。
- Document 含 id/source_id/title/url/category/content/status/revision/published_content/updated_at/vector_status。
- GET `/products?q=` → Product[]；PATCH `/products/{id}` 可编辑审核字段；POST `/products/{id}/publish`。
- Product 含 id/name/sku/country/card_type/days/data_allowance/price/original_price/currency/url/status/verified_at；未知字段为 null。
- GET `/sources` 的 Source 含 id/name/url/status/max_pages/last_synced；Job 含 id/source_id/status/progress/error/result/created_at。

## AI 和通道

- GET `/integrations` → `{chat:{configured,provider,model,display_name,reasoning_effort},embedding:{configured,model,dimensions},reranker:{configured,model},whatsapp:{configured,enabled,provider,instance}}`，不回傳憑證。`qwen` 僅為相容 `chat` 的別名，並非另一個正在使用的對話模型。
- POST `/ai/preview` `{question}` → AIResult；POST `/ai/probe` → 可达性结果（只读调用）
- AIResult `{answer,citations:[{id,title,url}],status,trace:[string],retrieval_mode}`；无配置/服务不可用要返回明确错误，不回传假答案。
- OpenCode 使用自己的 User-Agent 和經部署命名空間雜湊的穩定會話識別；不傳原始登入Token，不回傳供應者的 reasoning_content。high 為送往對話供應者的推理設定，與向量維度無關。
- GET `/whatsapp/status` → 通道只读状态；POST `/webhooks/evolution` 通过独立 webhook secret 校验。
- 没有 UI 保存凭证 API；凭证只能在被忽略的本机 .env 管理，设置页只显示状态和说明。

角色：`admin` 管理全部本地功能；`knowledge_manager` 管理知识/商品；`agent` 客服。知识写入需 admin/knowledge_manager，读取和会话操作需登录。sandbox 只允许 admin。所有真实外发需独立配置开关及授权，本轮不开启。
