import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import make_engine
from app.main import create_app
from app.models import Contact, Document, Message, User
from app.security import hash_password


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "testing-only-password-123")
    monkeypatch.setattr(settings, "qwen_base_url", "")
    monkeypatch.setattr(settings, "embedding_base_url", "")
    monkeypatch.setattr(settings, "evolution_base_url", "")
    monkeypatch.setattr(settings, "evolution_api_key", "")
    monkeypatch.setattr(settings, "evolution_instance", "")
    monkeypatch.setattr(settings, "allow_external_send", False)
    engine = make_engine("sqlite:///:memory:")
    app = create_app(engine)
    with TestClient(app) as test:
        yield test
    engine.dispose()


def login(client, name="admin", password="testing-only-password-123"):
    result = client.post("/api/auth/login", json={"username": name, "password": password})
    assert result.status_code == 200, result.text
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return result


def test_authentication_csrf_logout(client):
    assert client.get("/api/contacts").status_code == 401
    response = login(client)
    assert "HttpOnly" in response.headers["set-cookie"]
    token = client.headers.pop("X-CSRF-Token")
    assert client.post("/api/sandbox").status_code == 403
    client.headers["X-CSRF-Token"] = token
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_cross_origin_login_rejected(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "testing-only-password-123"}, headers={"Origin": "https://foreign.invalid"})
    assert response.status_code == 403


def test_system_validation_messages_are_traditional_chinese(client):
    response = client.post("/api/auth/login", json={})
    assert response.status_code == 422
    assert response.json()["detail"] == "請填寫帳號；請填寫密碼"
    assert client.get("/api/nonexistent").json()["detail"] == "找不到頁面或資料"
    login(client)
    response = client.post("/api/documents", json={"title": "短", "content": "short"})
    assert "標題至少需要 2 個字元" in response.json()["detail"]


def test_invalid_login_and_rate_limit(client):
    for _ in range(15):
        assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 429


def test_contact_persistence_and_duplicate(client):
    login(client)
    payload = {"display_name": "測試客戶", "phone": "+85200000000", "tags": ["日本"], "attributes": {"天數": "7"}}
    result = client.post("/api/contacts", json=payload)
    assert result.status_code == 201
    assert client.get("/api/contacts?q=00000000").json()[0]["attributes"] == {"天數": "7"}
    assert client.post("/api/contacts", json=payload).status_code == 409
    assert client.post("/api/contacts", json={"display_name": " ", "phone": "123"}).status_code == 422


def test_sandbox_message_idempotency_and_notes(client):
    login(client)
    identity = client.post("/api/sandbox").json()["id"]
    payload = {"body": "本地訊息", "internal": False, "idempotency_key": "case-message-001"}
    first = client.post(f"/api/conversations/{identity}/messages", json=payload)
    second = client.post(f"/api/conversations/{identity}/messages", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "simulated"
    payload["body"] = "不同內容"
    assert client.post(f"/api/conversations/{identity}/messages", json=payload).status_code == 409
    payload.update(internal=True, idempotency_key="case-note-002")
    assert client.post(f"/api/conversations/{identity}/messages", json=payload).json()["direction"] == "internal"
    assert len(client.get(f"/api/conversations/{identity}").json()["messages"]) == 2


def test_live_send_blocked_but_internal_note_works(client):
    login(client)
    contact = client.post("/api/contacts", json={"display_name": "指定測試", "phone": "test-only-123"}).json()
    identity = client.post("/api/conversations", json={"contact_id": contact["id"]}).json()["id"]
    payload = {"body": "不應外發", "internal": False, "idempotency_key": "case-blocked-001"}
    assert client.post(f"/api/conversations/{identity}/messages", json=payload).status_code == 409
    payload["internal"] = True
    assert client.post(f"/api/conversations/{identity}/messages", json=payload).status_code == 200
    assert client.post(f"/api/conversations/{identity}/simulate", json={"body": "no"}).status_code == 403


def test_agent_cannot_manage_knowledge_or_create_users(client):
    login(client)
    sandbox_id = client.post("/api/sandbox").json()["id"]
    response = client.post("/api/users", json={"username": "agent1", "display_name": "客服", "role": "agent", "password": "agent-testing-only-123"})
    assert response.status_code == 201
    assert "password_hash" not in response.json()
    client.post("/api/auth/logout")
    login(client, "agent1", "agent-testing-only-123")
    assert client.get("/api/documents").status_code == 200
    assert client.post("/api/documents", json={"title": "測試文件", "content": "This is a sufficiently long test content."}).status_code == 403
    assert client.post("/api/sandbox").status_code == 403
    assert client.get(f"/api/conversations/{sandbox_id}").status_code == 403
    assert client.post(f"/api/conversations/{sandbox_id}/messages", json={"body": "no", "internal": True, "idempotency_key": "forbidden-sandbox"}).status_code == 403
    assert not client.get("/api/conversations").json()


def test_document_draft_publish_revision_and_withdraw(client):
    login(client)
    payload = {"title": "測試文件", "content": "僅供測試的知識內容，請不要用作真正客服資料。", "url": "https://www.cooldatasim.com/", "category": "測試"}
    doc = client.post("/api/documents", json=payload).json()
    assert doc["published_content"] is None
    published = client.post(f"/api/documents/{doc['id']}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["published_content"] == payload["content"]
    payload["content"] = "更新的待審核測試資料，不應立即取代已發布內容。"
    changed = client.patch(f"/api/documents/{doc['id']}", json=payload).json()
    assert changed["status"] == "draft"
    assert changed["published_content"] != changed["content"]
    withdrawn = client.post(f"/api/documents/{doc['id']}/withdraw")
    assert withdrawn.status_code == 200


def test_sync_job_duplicate_requests_are_coalesced(client):
    login(client)
    identity = client.get("/api/sources").json()[0]["id"]
    first = client.post(f"/api/sources/{identity}/sync").json()
    second = client.post(f"/api/sources/{identity}/sync").json()
    assert first["id"] == second["id"]


def test_unknown_model_is_not_reported_as_ready(client):
    login(client)
    assert client.get("/api/integrations").json()["qwen"]["configured"] is False
    result = client.post("/api/ai/preview", json={"question": "日本七天套餐多少錢？"})
    assert result.status_code == 503


def test_manual_handoff_blocks_ai_suggestion(client):
    login(client)
    identity = client.post("/api/sandbox").json()["id"]
    client.post(f"/api/conversations/{identity}/simulate", json={"body": "請問套餐"})
    client.patch(f"/api/conversations/{identity}", json={"mode": "manual"})
    assert client.post(f"/api/conversations/{identity}/suggest").status_code == 409


def test_webhook_rejects_missing_secret(client):
    assert client.post("/api/webhooks/evolution", json={"event": "messages.upsert"}).status_code == 401


def test_long_conversation_keeps_latest_messages(client):
    login(client)
    identity = client.post("/api/sandbox").json()["id"]
    with client.app.state.session_factory() as db:
        db.add_all(Message(conversation_id=identity, body=f"message-{i}", direction="incoming", sender_type="customer") for i in range(505))
        db.commit()
    data = client.get(f"/api/conversations/{identity}").json()
    assert len(data["messages"]) == 500
    assert data["messages"][0]["body"] == "message-5"
    assert data["messages"][-1]["body"] == "message-504"
    assert data["messages_has_more"] is True
