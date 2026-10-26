# TASK-004：接通獨立向量與重排服務

## 狀態

本項接通與隔離驗收已完成，待人工Review；整體客服系統仍有未完成項。使用者明確要求在模型電腦提供獨立 Embedding／Reranker 接口並接通本後台，本任務新增服務及本機連線的授權取代先前僅限只讀的相關限制。

## 背景

目前對話使用 DeepSeek V4.1 Flash high；Qwen3-Embedding-0.6B／Qwen3-Reranker-0.6B 的既有模型檔已存在，但員工知識庫沒有獨立模型接口。需要讓本專案使用模型推理能力，保持資料與業務指令隔離。

## 驗收標準

- 模型電腦新增獨立、CPU限定、僅監聽loopback的服務，提供已驗證身份的 `/v1/embeddings`、`/v1/rerank`、`/v1/models`。
- 讀取既有模型檔；不查詢員工文件/索引、不改員工服務或其他GPU服務。
- 新服務使用本專案獨立的隨機憑證，透過已有SSH通道連接本機Docker後台。
- 實際產生1024維有限非零向量；重排回傳有效排名。
- 以本專案隔離測試資料完成發布向量化、PostgreSQL儲存、相似度檢索、重排及DeepSeek回答，結束後清理測試資料。
- 後台清楚顯示已設定/探測/實際推理狀態；真實網站草稿不自動發布。

## 允許修改

- `infra/vector-service/`：獨立API、CPU模型推理、服務單元及必要測試/說明。
- `scripts/vector_tunnel.py`、`scripts/model_tunnel.py`、`scripts/deploy_vectors.py`、`scripts/app.py`、`tests/test_vector_tunnel.py`
- `backend/app/ai.py`、`backend/tests/test_knowledge.py`：查詢與文件向量用途區分及必要適配。
- `scripts/project.py`、`tests/test_repository.py`、`compose.yaml`、`.env.example`
- `README.md`、`AGENTS.md`、`docs/ARCHITECTURE.md`、`docs/REQUIREMENTS.md`、`docs/RUNBOOK.md`、`docs/API.md`
- `docs/TASKS/README.md`、`docs/TASKS/TASK-004.md`、`docs/DECISIONS/README.md`、`docs/DECISIONS/ADR-006-vector-service.md`
- `docs/TASKS/TASK-003.md`：只追加向量接通里程碑，不改寫歷史驗證結果。
- 被忽略的 `.env`、`.env.vector-tunnel.json`、`.env.vector-tunnel.pid` 和 outputs 下的運行記錄。

遠端僅允許新目錄 `/home/ubuntu/ai/workspace/cooldatasim-vector-api/`、新使用者服務 `cooldatasim-vector-api.service`；既有模型檔和Python環境只讀使用。

## 禁止修改

員工知識庫文件/資料庫/程式、既有模型檔、MiniMax H3/ComfyUI/Qwen對話服務、AWS設定、WhatsApp帳號、Git提交與推送。不得把模型API密鑰或SSH密鑰寫入版本庫及鏡像。

## 操作權限

允許部署和啟動上述獨立CPU服務、建立本專案憑證、本機SSH轉發、更新本專案Docker環境、執行隔離聯調。此次不需要切換GPU模型或停止其他服務。

## 執行計劃

1. 核對遠端資源、唯讀模型路徑、Python依賴和可用連接埠。
2. 實作獨立API並部署只屬於本專案的使用者服務。
3. 建立雙跳SSH轉發，更新本機向量/重排設定並載入。
4. 執行直接接口及完整後台流程驗證，記錄結果與未完成項。

## 驗證命令

```sh
python scripts/deploy_vectors.py deploy
python scripts/app.py build
python scripts/app.py up
python scripts/app.py verify
python scripts/project.py check
```

真實接口驗證透過本機私有轉發呼叫；完整鏈路透過/api/documents和/api/ai/preview使用隔離文件。模型憑證由本機.env讀取，不顯示在命令或報告中。

## 驗證結果

日期：2026-10-24（Asia/Shanghai），分支ai/TASK-004。

- 獨立cooldatasim-vector-api.service為active且enabled，loopback8195，CPU模式；使用唯讀既有模型檔與Python執行環境。API不保存輸入，health顯示storage=none、knowledge_access=false。
- 模型電腦GPU設定保持h3，員工RAG健康仍為ready；沒有修改原有服務或GPU模型。
- 真實接口：未授權呼叫被401拒絕，384維請求被422拒絕。文件及查詢向量皆為1024維、有限非零、範數接近1；相關文件相似度高於無關文件。真實重排相關文件排名第一；直接驗證約5.32秒。
- 本機Docker經雙跳SSH可讀取兩個模型清單，Embedding/Reranker均為listed。對話仍使用deepseek-v4.1-flash high。
- 完整真實鏈路：兩份隔離測試文檔發布後vector_status=indexed，PostgreSQL實際保存兩個1024維向量及正確模型身份。查詢生成向量、原生餘弦查詢、Qwen重排、DeepSeek回答和正確引用均通過，retrieval_mode=hybrid，整段約11.14秒。
- 測試文件及向量已撤回並清理。實際網站仍有10份待審文檔，0份已發布，沒有將網站草稿自動發布。
- 瀏覽器設定頁確認兩個模型已配置，連通檢查成功，無JavaScript執行錯誤。截圖outputs/screenshots/23-vector-connected.png。
- 本機轉發重啟驗證：停止本專案轉發後，app.py up自動啟動新進程並恢復已驗證身份的模型訪問；沒有新增Windows啟動排程。
- `python scripts/project.py check`通過：43項治理/部署/轉發測試，95項後端及27項獨立模型API測試（合計122），17項前端測試、型別檢查及正式構建。
- 端到端紀錄：outputs/vector-integration-report.json。沒有提交、推送或執行AWS部署。

未覆蓋：大量並發、長期穩定性、全站知識品質、真實網站發布後完整業務問答、AWS端網路及其他既有未完成模組。不能將本項接通當成整體專案通過。

## 人工驗收與風險

新增遠端服務、身份驗證和SSH路徑需重點Review。模型推理使用CPU與獨立進程，會額外使用記憶體；部署前核對資源。真實網站知識仍待人工審核，整體客服系統不因向量接通就標記完成。
