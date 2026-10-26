"""Authenticated, storage-free CPU Embedding/Reranker service."""

from contextlib import asynccontextmanager, contextmanager
import hmac
import os
from pathlib import Path
import threading
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictStr, field_validator

from inference import CpuModels, DIMENSIONS, EMBEDDING_MODEL, RERANKER_MODEL, checked_scores, checked_vectors


class EmbeddingRequest(BaseModel):
    model: Literal[EMBEDDING_MODEL]
    input: StrictStr | list[StrictStr]
    dimensions: Literal[DIMENSIONS] = DIMENSIONS
    input_type: Literal["query", "document"] = "document"

    @field_validator("input")
    @classmethod
    def bounded_text(cls, value):
        texts = [value] if isinstance(value, str) else value
        if not 1 <= len(texts) <= 16 or any(not text.strip() or len(text) > 8000 for text in texts):
            raise ValueError("請提供1至16段非空白文字，每段最多8000字元")
        return value


class RerankRequest(BaseModel):
    model: Literal[RERANKER_MODEL]
    query: str = Field(min_length=1, max_length=8000)
    documents: list[StrictStr] = Field(min_length=1, max_length=32)
    top_n: int = Field(default=6, ge=1, le=32)

    @field_validator("query")
    @classmethod
    def non_blank_query(cls, value):
        if not value.strip():
            raise ValueError("問題不可空白")
        return value

    @field_validator("documents")
    @classmethod
    def bounded_documents(cls, value):
        if any(not item.strip() or len(item) > 8000 for item in value):
            raise ValueError("重排文件不可空白，每段最多8000字元")
        return value


def create_app(*, runner=None, api_key=None):
    @asynccontextmanager
    async def lifespan(app):
        key = api_key if api_key is not None else os.environ.get("VECTOR_API_KEY", "")
        if len(key) < 32 or any(character.isspace() for character in key):
            raise RuntimeError("請先設定獨立的模型API憑證")
        app.state.api_key = key
        app.state.inference_lock = threading.Lock()
        app.state.runner = runner if runner is not None else CpuModels(
            Path(os.environ.get("VECTOR_MODEL_ROOT", "/home/ubuntu/ai/workspace/employee-rag/models")),
            threads=int(os.environ.get("VECTOR_CPU_THREADS", "8")),
            max_tokens=int(os.environ.get("VECTOR_MAX_TOKENS", "2048")),
            dtype=os.environ.get("VECTOR_DTYPE", "bfloat16"))
        yield

    app = FastAPI(title="Cool Data Sim 獨立向量服務", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def bounded_body(request, call_next):
        if request.method == "POST":
            length = request.headers.get("content-length", "0")
            if not length.isdecimal() or int(length) > 1_000_000:
                return JSONResponse({"detail": "請求資料過大"}, status_code=413)
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 1_000_000:
                    return JSONResponse({"detail": "請求資料過大"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo request text or credentials in Pydantic's default detail.
        return JSONResponse({"detail": "請檢查模型名稱、維度、文字長度與批次範圍"}, status_code=422)

    @app.exception_handler(Exception)
    async def inference_error(request, exc):
        return JSONResponse({"detail": "模型推理暫時無法完成，請稍後再試"}, status_code=500)

    def authenticate(request: Request):
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if not token or not hmac.compare_digest(token, app.state.api_key):
            raise HTTPException(401, "模型API憑證無效", headers={"WWW-Authenticate": "Bearer"})

    @contextmanager
    def inference_slot():
        if not app.state.inference_lock.acquire(blocking=False):
            raise HTTPException(429, "模型正在處理其他請求，請稍後重試", headers={"Retry-After": "1"})
        try:
            yield
        finally:
            app.state.inference_lock.release()

    @app.get("/health")
    def health():
        return {"status": "ready", "device": "cpu", "dimension": DIMENSIONS,
                "embedding": EMBEDDING_MODEL, "reranker": RERANKER_MODEL,
                "storage": "none", "knowledge_access": False}

    @app.get("/v1/models", dependencies=[Depends(authenticate)])
    def models():
        return {"object": "list", "data": [{"id": name, "object": "model", "owned_by": "cooldatasim"}
                                             for name in (EMBEDDING_MODEL, RERANKER_MODEL)]}

    @app.post("/v1/embeddings", dependencies=[Depends(authenticate)])
    def embeddings(payload: EmbeddingRequest):
        texts = [payload.input] if isinstance(payload.input, str) else payload.input
        with inference_slot():
            try:
                vectors, token_count = app.state.runner.embed(texts, query=payload.input_type == "query")
            except ValueError:
                raise HTTPException(422, "文字超過模型Token上限，請縮短問題或分段") from None
            checked_vectors(vectors, len(texts))
        return {"object": "list", "model": EMBEDDING_MODEL,
                "data": [{"object": "embedding", "index": index, "embedding": vector}
                         for index, vector in enumerate(vectors)],
                "usage": {"prompt_tokens": token_count, "total_tokens": token_count},
                "input_type": payload.input_type}

    @app.post("/v1/rerank", dependencies=[Depends(authenticate)])
    def rerank(payload: RerankRequest):
        with inference_slot():
            try:
                scores = app.state.runner.rerank(payload.query, payload.documents)
            except ValueError:
                raise HTTPException(422, "問題與文件超過重排Token上限，請縮短或分段") from None
            scores = checked_scores(scores, len(payload.documents))
        indexes = sorted(range(len(scores)), key=lambda index: (-scores[index], index))[:payload.top_n]
        return {"model": RERANKER_MODEL,
                "results": [{"index": index, "relevance_score": scores[index]} for index in indexes]}

    return app


app = create_app()
