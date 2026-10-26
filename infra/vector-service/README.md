# Cool Data Sim 獨立CPU模型接口

本服務只讀取Qwen模型檔並執行推理，不讀取員工資料、文件、向量索引或其業務程式，也不提供知識搜尋。僅應綁定loopback並透過受控SSH通道存取。

## 運行設定

| 環境變數 | 用途 | 預設 |
| --- | --- | --- |
| VECTOR_API_KEY | 本專案獨立Bearer憑證，至少32字元 | 必填，勿放版本庫 |
| VECTOR_MODEL_ROOT | 既有模型目錄，內含兩個模型子目錄 | /home/ubuntu/ai/workspace/employee-rag/models |
| VECTOR_CPU_THREADS | 此獨立進程的CPU執行緒 | 8，允許1至32 |
| VECTOR_MAX_TOKENS | 每段實際Token上限，超過會拒絕，不靜默截斷 | 2048 |
| VECTOR_DTYPE | CPU權重型別 | bfloat16，可選float32 |

使用現有可讀的Python模型環境，**不在原環境執行pip安裝或更新**。所需函式庫為FastAPI/Pydantic、Uvicorn、PyTorch、Transformers（Qwen3支援需>=4.51.0）及本機模型檔。部署時記錄既有環境版本；若不相容，建立本專案獨立環境後再處理。

```sh
python -m uvicorn vector_api:app --host 127.0.0.1 --port 8195 --workers 1 --no-access-log
```

啟動時載入兩個模型，CUDA明確停用、模型不下載、無遠端自訂程式碼。每次只處理一個推理請求；忙碌時回傳429與Retry-After。

## HTTP契約

- GET `/health`：啟動完成才回傳ready；不代表已驗證某組業務問答品質。
- GET `/v1/models`：需Bearer憑證，回傳Embedding與Reranker的模型識別。
- POST `/v1/embeddings`：`{model:"Qwen3-Embedding-0.6B",input:["文字"],dimensions:1024,input_type:"query"或"document"}`。批次最多16段，每段最多8000字元；另受Token上限限制。
- POST `/v1/rerank`：`{model:"Qwen3-Reranker-0.6B",query:"問題",documents:["文件"],top_n:6}`。最多32段文件，回傳原始index與0至1相關分數。

查詢使用Cool Data Sim專用檢索指令，文件不加查詢指令。向量採最後有效Token池化後L2正規化；重排採yes/no判斷機率，計算最後位置的兩個輸出權重，不建立全序列詞彙輸出矩陣。

官方依據：[Embedding模型卡](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)、[Reranker模型卡](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)。

## 本機接口測試

測試使用注入的模擬推理器，不需要Torch或模型檔；只驗證身份、格式、限制及回應檢查，不能當成真實推理通過。

```sh
.venv/Scripts/python.exe -m pytest infra/vector-service/test_vector_api.py -q
```

實際部署及真實1024維向量、重排和後台聯調由TASK-004另外記錄。
