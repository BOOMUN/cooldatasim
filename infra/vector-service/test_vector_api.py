"""API contract tests with an injected runner, never real model inference."""

import math
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vector_api import create_app
from inference import DIMENSIONS, EMBEDDING_MODEL, RERANKER_MODEL, checked_scores, checked_vectors

KEY = "test-only-" + "x" * 40
HEADERS = {"Authorization": "Bearer " + KEY}


class FakeRunner:
    def __init__(self):
        self.calls = []

    def embed(self, texts, *, query=False):
        self.calls.append(("embed", texts, query))
        return [[1.0] + [0.0] * (DIMENSIONS - 1) for _ in texts], sum(len(text) for text in texts)

    def rerank(self, query, documents):
        self.calls.append(("rerank", query, documents))
        return [0.1 + index / max(1, len(documents)) for index in range(len(documents))]


@pytest.fixture
def runner():
    return FakeRunner()


@pytest.fixture
def client(runner):
    app = create_app(runner=runner, api_key=KEY)
    with TestClient(app) as client:
        yield client


def embedding_payload(**changes):
    return {"model": EMBEDDING_MODEL, "input": ["測試文件"], "dimensions": 1024, **changes}


def rerank_payload(**changes):
    return {"model": RERANKER_MODEL, "query": "啟用說明", "documents": ["旅行資訊", "上網卡啟用說明"], **changes}


def test_health_has_no_knowledge_store(client):
    result = client.get("/health").json()
    assert result["status"] == "ready"
    assert result["device"] == "cpu"
    assert result["dimension"] == 1024
    assert result["knowledge_access"] is False
    assert result["storage"] == "none"


def test_models_require_separate_bearer(client):
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer invalid"}).status_code == 401
    result = client.get("/v1/models", headers=HEADERS).json()
    assert [row["id"] for row in result["data"]] == [EMBEDDING_MODEL, RERANKER_MODEL]
    assert KEY not in str(result)


def test_embedding_returns_valid_document_vectors(client, runner):
    result = client.post("/v1/embeddings", headers=HEADERS, json=embedding_payload(input=["第一段", "第二段"]))
    assert result.status_code == 200
    value = result.json()
    assert value["model"] == EMBEDDING_MODEL
    assert [row["index"] for row in value["data"]] == [0, 1]
    assert len(value["data"][0]["embedding"]) == 1024
    assert math.isclose(sum(v * v for v in value["data"][0]["embedding"]), 1)
    assert value["input_type"] == "document"
    assert runner.calls == [("embed", ["第一段", "第二段"], False)]


def test_query_type_is_explicit(client, runner):
    response = client.post("/v1/embeddings", headers=HEADERS, json=embedding_payload(input="日本七日套餐", input_type="query"))
    assert response.status_code == 200
    assert runner.calls == [("embed", ["日本七日套餐"], True)]


@pytest.mark.parametrize("changes", [
    {"model": "different-model"}, {"dimensions": 384}, {"input_type": "employee"},
    {"input": []}, {"input": ["x"] * 17}, {"input": " "}, {"input": ["x" * 8001]},
    {"input": [123]},
])
def test_invalid_embedding_input_rejected_without_echo(client, runner, changes):
    response = client.post("/v1/embeddings", headers=HEADERS, json=embedding_payload(**changes))
    assert response.status_code == 422
    assert runner.calls == []
    assert "input" not in response.json()
    assert "請檢查" in response.json()["detail"]


def test_unauthorized_calls_never_infer(client, runner):
    assert client.post("/v1/embeddings", json=embedding_payload()).status_code == 401
    assert client.post("/v1/rerank", json=rerank_payload()).status_code == 401
    assert runner.calls == []


def test_rank_result_preserves_original_indexes(client):
    response = client.post("/v1/rerank", headers=HEADERS, json=rerank_payload(top_n=1))
    assert response.status_code == 200
    assert response.json()["model"] == RERANKER_MODEL
    assert response.json()["results"] == [{"index": 1, "relevance_score": 0.6}]


@pytest.mark.parametrize("changes", [
    {"model": EMBEDDING_MODEL}, {"documents": []}, {"documents": ["x"] * 33},
    {"query": " "}, {"documents": [""]}, {"top_n": 0}, {"top_n": 33},
])
def test_invalid_rerank_input_rejected(client, runner, changes):
    assert client.post("/v1/rerank", headers=HEADERS, json=rerank_payload(**changes)).status_code == 422
    assert runner.calls == []


def test_busy_returns_429_without_second_inference(client, runner):
    lock = client.app.state.inference_lock
    lock.acquire()
    try:
        response = client.post("/v1/embeddings", headers=HEADERS, json=embedding_payload())
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "1"
        assert runner.calls == []
    finally:
        lock.release()


def test_invalid_runtime_vector_not_reported_as_success():
    class BrokenRunner(FakeRunner):
        def embed(self, texts, *, query=False):
            return [[0.0] * 1024], 1

    with TestClient(create_app(runner=BrokenRunner(), api_key=KEY), raise_server_exceptions=False) as client:
        response = client.post("/v1/embeddings", headers=HEADERS, json=embedding_payload())
        assert response.status_code == 500
        assert response.json()["detail"] == "模型推理暫時無法完成，請稍後再試"


def test_token_limit_is_visible_and_lock_is_released():
    class LimitedRunner(FakeRunner):
        def embed(self, texts, *, query=False):
            raise ValueError("private-input-that-must-not-be-echoed")

    with TestClient(create_app(runner=LimitedRunner(), api_key=KEY)) as client:
        response = client.post("/v1/embeddings", headers=HEADERS, json=embedding_payload())
        assert response.status_code == 422
        assert "private-input" not in response.text
        assert not client.app.state.inference_lock.locked()


def test_oversized_body_is_rejected(client, runner):
    response = client.post("/v1/embeddings", headers=HEADERS, content=b" " * 1_000_001)
    assert response.status_code == 413
    assert runner.calls == []


def test_missing_key_refuses_startup():
    with pytest.raises(RuntimeError, match="憑證"):
        with TestClient(create_app(runner=FakeRunner(), api_key="")):
            pass


def test_vector_and_score_checkers_reject_invalid_outputs():
    for vector in ([0] * 1024, [float("nan")] * 1024, [1] * 384):
        with pytest.raises(RuntimeError):
            checked_vectors([vector], 1)
    for scores in ([float("inf")], [-0.1], [1.1], []):
        with pytest.raises(RuntimeError):
            checked_scores(scores, 1)
