# TASK-003：开发并部署本机客服后台首版

## 状态

進行中，部分功能已實作並完成本機範圍驗證；整體專案及本任務未標記完成。使用者已授權確定方案並開發，並明確要求未完成項不得標記完成，系統文字採繁體中文。

## 背景

本機獨立 PostgreSQL/pgvector 已部署。當前任務將需求落成可運行的 Vue + FastAPI 後台，重點為網站知識、結構化商品與 LangGraph/對話模型接入。使用者最新指定暫用 DeepSeek V4.1 Flash high；向量與 WhatsApp 未聯調的部分必須在介面和驗收中明確。

## 验收标准

- 本机可登录后台，具备收件箱、客户资料、知识库、商品资料、WhatsApp 和 AI 设置页面。
- 系統介面與面向使用者的後端提示採用繁體中文；不改寫客戶原始訊息或來源原文。
- 真实本机数据库持久化；角色和会话权限生效，内部备注不外发。
- 网站采集任务持久化，公开网站内容进入待审核区；已发布内容才可作为回答依据。
- 商品字段及来源可查看，价格不由模型臆造；采集未知字段保持空白。
- 使用真实 LangGraph 组织检索和生成，Qwen 对话/向量/重排分别配置；无服务时明确不可用，不假造答案或向量。
- 通道代码处理消息方向、去重及回执；真实外发默认禁用，号码联调状态不冒充完成。
- 完成本机容器部署、自动测试和浏览器基本流程验证；各模块分别标识已实现、已验证、待联调。

## 允许修改

- `backend/`：仅本项目新建应用、迁移、依赖、Dockerfile 和测试。
- `frontend/`：仅本项目新建 Vue 页面、类型、样式、构建和品牌资源。
- `scripts/app.py`、`scripts/project.py`、`tests/test_repository.py`
- `scripts/model_tunnel.py`、`tests/test_model_tunnel.py`：使用者後續授權配置 Qwen 的本機安全轉發與驗證。
- `compose.yaml`、`.env.example`、`.gitignore`、`.dockerignore`、`.github/workflows/ci.yml`
- `README.md`、`AGENTS.md`
- `docs/API.md`、`docs/ARCHITECTURE.md`、`docs/REQUIREMENTS.md`、`docs/RUNBOOK.md`
- `docs/TASKS/README.md`、`docs/TASKS/TASK-003.md`
- `docs/DECISIONS/README.md`、`docs/DECISIONS/ADR-003-stack.md`、`docs/DECISIONS/ADR-005-initial-app.md`
- `docs/DECISIONS/ADR-001-model-boundaries.md`：依使用者最新指定暫用 DeepSeek 對話模型，向量/重排仍獨立。

允许在被忽略的 .env 中追加本机应用凭证，保留已有数据库密码；构建和测试产物只放入忽略目录。同一任务可分配互不重叠的模块并行实现。

## 禁止修改

参考克隆、TASK-001/002 历史结果、其他项目容器/卷、AWS、模型电脑、真实 WhatsApp 账号。禁止 Git 提交推送、清空现有数据库或自动发布真实网站知识。

## 操作权限

授权本地业务开发、安装项目依赖、建立本项目业务表、拉取公开网站内容为草稿、本项目容器运行及隔离测试。真实 WhatsApp 发送/扫码关联、远端模型切换和 AWS 迁移仍需独立授权。

## 执行计划

1. 固定接口契约、模块职责和默认权限；前端、知识/AI、通道分别实现。
2. 建立数据库模型、登录/权限、客户会话接口和部署脚本。
3. 完成网站采集、审核发布、商品查询、LangGraph AI 预览和受控消息路径。
4. 运行单元/接口/浏览器验证，记录真实失败和未联调能力。

## 验证命令

```sh
python scripts/project.py check
python scripts/app.py prepare
python scripts/app.py build
python scripts/app.py up
python scripts/app.py verify
python scripts/app.py package
```

check 包含治理單元測試、後端 pytest、前端 npm test、型別檢查與正式構建。外部模型和真實號碼須另外聯調，不計入這些結果。

## 验证结果

驗證基準：2026-10-24（Asia/Shanghai），分支 ai/TASK-003，本機 linux/amd64 容器，沒有提交或遠端 CI 記錄。

| 模組 | 實際狀態 | 證據與限制 |
| --- | --- | --- |
| 登入、會話、CSRF、角色 | 已實作，本機及隔離測試通過 | 管理員/客服/知識管理員；未完成生產安全與負載驗收 |
| 客戶、會話、內部備註、分配 | 已實作，本機驗證 | 只有明確的演練資料；沒有真實 WhatsApp 外發 |
| 繁體中文系統文案 | 已實作並驗證 | 介面、裝飾文字、狀態、表單與錯誤提示；客戶/網站原文不轉換 |
| 網站草稿採集 | 有限批次已驗證 | 正式本機 PostgreSQL Job #2 處理 10 頁，仍有 64 個發現連結未處理，full_site_verified=false |
| 文檔/商品資料 | 本機已有 10 份文檔、8 項商品 | 全部待審核，0 份真實網站知識發布；不是全站資料或內容品質通過 |
| 文檔發布、草稿修訂、撤回 | 已實作，隔離本機資料驗證 | 舊快照保留和撤回已驗證；測試資料已清理；真實資料未自動發布 |
| 商品審閱 | UI/解析/條件篩選已測 | 真實商品發布未執行，變體價格、庫存及價格歷史未完成 |
| LangGraph/對話模型 | DeepSeek V4.1 Flash high 已實際呼叫 | 經 OpenCode 和本機完整Graph驗證缺資料轉人工及隔離文件引用；Qwen對話仍503，未切換模型電腦服務 |
| 向量與重排 | 1024維儲存及適配碼已具備 | 既有員工RAG健康回傳ready，但新後台標準模型介面尚未接通；未生成真實知識向量 |
| Evolution通道 | 協定處理已測 | 去重、手機方向、回執為模擬協定測試；沒有真實號碼關聯或收發 |
| 本機部署與打包 | 已運行並驗證 | API/Worker/PostgreSQL正常，鏡像包可校驗與重新載入；AWS未執行 |

實際驗證結果：

- `python scripts/project.py check` 通過：27 項治理/部署工具測試、77 項後端測試、13 項前端測試，Vue/TypeScript 檢查與正式構建通過。
- 瀏覽器實際走過登入/重新整理/登出、全部導航、演練訊息與備註持久化、客戶/文檔/商品彈窗、手機窄螢幕和未配置狀態。報告為 outputs/screenshots/browser-report.json；隔離攔截回應的UI測試已與真實API驗證分開記錄。
- 最終已部署鏡像另驗證英語瀏覽器環境下的繁體原生表單提示、登入、知識庫/設定及登出，無 JavaScript 執行錯誤。截圖20/21為實際本機服務。
- 實際PostgreSQL接口驗證客戶編輯保存、隔離測試文檔發布→修改草稿保留舊快照→撤回；測試文檔與客戶已清理，真實網站草稿保留。
- Shopline正文清洗抽查商品、FAQ、首頁及回歸fixture；導覽/購物車/語言貨幣/隱藏庫存模板已排除。其餘頁面、圖片文字及動態內容仍待審核。
- 最終應用+資料庫預覽鏡像包：outputs/app-releases/20261024T065306Z-0cf679，約232.3 MiB。SHA-256及重新載入後鏡像ID一致；未含.env、備份或模型權重。
- 當前業務資料備份：outputs/backups/20261024T065515Z-d71840/cooldatasim.dump，歸檔目錄校驗通過。此次業務資料的完整恢復未驗證，不能沿用TASK-002的基礎結構恢復結果代替。

仍未完成：Qwen真實推理、Embedding/Reranker介面接入、真實WhatsApp配對/手機同步/媒體/引用/回應/編輯撤回/歷史補拉/群聊/通話、AI自動外發、全站覆蓋、PDF/圖片與動態內容採集、定時同步、版本回退、商品變價歷史、完整歷史分頁、SSE即時通知、匯入匯出、AWS部署及正式負載驗收。上述項目不得標記完成。

## 人工验收与风险

权限、初始建表、模型凭证和消息发送是重点 Review 项。首版只绑定本机；没有真实服务证据时任务保持部分完成，不能用界面或 mock 测试替代真实联调。

使用者後續明確授權變更本機 admin 登入密碼。已更新密碼雜湊、撤銷原有管理員登入階段，並以指定新密碼完成實際登入驗證；密碼不記錄在版本庫。保留初始化環境變數，重啟不會重設已有帳號。此操作不代表其他未完成模組已完成。

## 後續對話模型設定與向量核查

使用者先要求配置 Qwen，隨後指定暫用 DeepSeek V4.1 Flash high，並詢問向量模型是否能呼叫。以最新選擇為準：

- 本機 CHAT_* 已設定 OpenCode 提供的 deepseek-v4.1-flash，reasoning_effort=high、thinking enabled。憑證僅寫入被忽略的 .env，不在程式、文件或鏡像中。
- 真實供應者 /models 回傳200，含指定模型；補齊官方要求的穩定會話識別和真實User-Agent後，chat/completions回傳200、finish_reason=stop、有效JSON。未讀取或顯示reasoning_content。
- 更新本機API/Worker後，/api/ai/probe回報chat模型已列出；/api/ai/preview實際經LangGraph呼叫成功。無發布資料時needs_human=true；隔離測試文件可正確回答並引用，實測約2.08及2.37秒。
- 測試文件已撤回並清理；真實網站草稿保持未發布。檢索模式明確為keyword，不能算向量檢索通過。
- 瀏覽器已驗證顯示DeepSeek實際型號與獨立Qwen向量/重排卡片，無JavaScript執行錯誤；截圖outputs/screenshots/22-deepseek-high-settings.png。
- 最新自動檢查：31項治理/部署/轉發測試、91項後端測試、17項前端測試及正式構建通過。
- 只讀核查現有員工RAG：Embedding/Reranker健康為ready、CPU、1024維，但路由只有員工資料/文件/search/ask，沒有獨立embeddings/rerank接口。本後台向量與重排設定仍為未配置。
- 未切換模型電腦的MiniMax H3或Qwen，沒有新增遠端服務。暫建的本機Qwen SSH轉發已停止，保留工具及私有設定供未來明確授權使用。

整體任務仍未完成；本次只將「目前對話模型的真實接入」提升為已驗證，向量/重排、WhatsApp、全站資料與AWS等原有未完成項保持不變。

## 後續向量接入里程碑

上述向量未接通為先前檢查結果。使用者後續明確授權TASK-004，在模型電腦新增獨立CPU接口並接通本機後台；目前Embedding/Reranker已通過真實向量、PostgreSQL儲存、混合檢索、重排與DeepSeek引用驗證。詳見[TASK-004](TASK-004.md)。本卡整體仍進行中，WhatsApp、全站資料與其他未完成項不變。
