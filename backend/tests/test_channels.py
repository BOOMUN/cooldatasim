"""Synthetic protocol tests only: no Evolution service or real account is used."""

import copy
import json
from urllib.error import URLError

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import channels
from app.config import Settings
from app.models import Base, Contact, Conversation, Message


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture(autouse=True)
def channel_settings(monkeypatch):
    settings = Settings(evolution_base_url="http://example.invalid", evolution_api_key="test-only",
                        evolution_instance="cool-test", webhook_secret="test-only-webhook",
                        allow_external_send=False)
    monkeypatch.setattr(channels, "settings", settings)
    # The entire suite is offline, including failures caused by accidental IO.
    def no_network(*args, **kwargs):
        raise AssertionError("Channel tests must not make network requests")
    monkeypatch.setattr(channels, "build_opener", no_network)
    return settings


def upsert(message_id="message-1", from_me=False, **overrides):
    item = {"key": {"id": message_id, "remoteJid": "85260000000@s.whatsapp.net", "fromMe": from_me},
            "pushName": "测试客户", "message": {"conversation": "日本上网套餐"},
            "status": "SERVER_ACK", "messageTimestamp": 1760000000}
    item.update(overrides)
    return {"event": "messages.upsert", "instance": "cool-test", "data": item}


def receipt(message_id="message-1", status="READ", instance="cool-test"):
    return {"event": "messages.update", "instance": instance,
            "data": {"keyId": message_id, "status": status}}


def test_unconfigured_status_does_not_call_provider(channel_settings):
    channel_settings.evolution_api_key = ""
    result = channels.channel_status()
    assert result["configured"] is False
    assert result["state"] == "not_configured"
    assert result["verified"] is False
    assert result["capabilities"]["media_send"] == "not_implemented"
    assert result["capabilities"]["history_sync"] == "not_implemented"


def test_status_is_read_only_and_not_sync_verification(monkeypatch):
    seen = []
    def response(method, path, payload=None):
        seen.append((method, path, payload))
        return {"instance": {"instanceName": "cool-test", "state": "open"}}
    monkeypatch.setattr(channels, "_request", response)
    result = channels.channel_status()
    assert seen == [("GET", "/instance/connectionState/cool-test", None)]
    assert result["state"] == "open"
    assert result["verified"] is False


def test_provider_state_error_is_visible_without_secret(monkeypatch):
    def unavailable(*args):
        raise channels.ChannelError("連線失敗", "upstream_unavailable")
    monkeypatch.setattr(channels, "_request", unavailable)
    result = channels.channel_status()
    assert result["state"] == "unavailable"
    assert "test-only" not in json.dumps(result)


def test_status_rejects_different_account_and_malformed_state(monkeypatch):
    monkeypatch.setattr(channels, "_request", lambda *args: {
        "instance": {"instanceName": "other", "state": "open"},
    })
    result = channels.channel_status()
    assert result["state"] == "unavailable"
    assert result["error_code"] == "instance_mismatch"
    monkeypatch.setattr(channels, "_request", lambda *args: {
        "instance": {"instanceName": "cool-test", "state": []},
    })
    assert channels.channel_status()["state"] == "unknown"


def test_webhook_secret_validation(channel_settings):
    assert channels.verify_webhook(b"{}", {"X-CoolDataSim-Webhook-Secret": "test-only-webhook"})
    assert not channels.verify_webhook(b"{}", {"x-cooldatasim-webhook-secret": "wrong"})
    assert not channels.verify_webhook(b"{}", {})
    assert not channels.verify_webhook(b"{}", {"x-cooldatasim-webhook-secret": ["test-only-webhook"]})
    channel_settings.webhook_secret = ""
    assert not channels.verify_webhook(b"{}", {"x-cooldatasim-webhook-secret": ""})


def test_duplicate_upsert_does_not_increment_unread(db):
    assert channels.ingest_webhook(db, upsert())["created"] == 1
    db.commit()
    assert channels.ingest_webhook(db, upsert())["duplicates"] == 1
    db.commit()
    assert db.scalar(select(func.count()).select_from(Message)) == 1
    assert db.scalar(select(Conversation)).unread_count == 1
    contact = db.scalar(select(Contact))
    assert contact.phone == "+85260000000"
    assert contact.wa_id == "85260000000@s.whatsapp.net"


def test_phone_message_syncs_outgoing_without_unread_or_ai(db):
    result = channels.ingest_webhook(db, upsert(from_me=True))
    assert result["created"] == 1
    message = db.scalar(select(Message))
    assert (message.direction, message.sender_type, message.status) == ("outgoing", "phone", "sent")
    assert message.metadata_json["ai_triggered"] is False
    assert db.scalar(select(Conversation)).unread_count == 0
    # fromMe pushName is often the business user's name, not the customer's.
    assert db.scalar(select(Contact)).display_name != "测试客户"


def test_account_namespace_and_wrong_instance_ignored(db, channel_settings):
    channels.ingest_webhook(db, upsert(from_me=True))
    assert channels.ingest_webhook(db, receipt(instance="different-account"))["ignored"] == 1
    assert db.scalar(select(Message)).status == "sent"
    second = upsert(from_me=True)
    second["instance"] = "another-account"
    assert channels.ingest_webhook(db, second)["ignored"] == 1
    channel_settings.evolution_instance = "another-account"
    assert channels.ingest_webhook(db, second)["created"] == 1
    messages = db.scalars(select(Message)).all()
    assert len(messages) == 2
    assert messages[0].external_id != messages[1].external_id


def test_out_of_order_receipts_never_downgrade(db):
    channels.ingest_webhook(db, upsert(from_me=True))
    assert channels.ingest_webhook(db, receipt(status="READ"))["updated"] == 1
    assert channels.ingest_webhook(db, receipt(status="DELIVERY_ACK"))["updated"] == 0
    assert channels.ingest_webhook(db, receipt(status="PENDING"))["updated"] == 0
    assert channels.ingest_webhook(db, receipt(status="ERROR"))["updated"] == 0
    assert db.scalar(select(Message)).status == "read"
    assert db.scalar(select(Conversation)).unread_count == 0


def test_nested_numeric_status_and_unknown_ids(db):
    channels.ingest_webhook(db, upsert(from_me=True))
    event = {"event": "MESSAGES_UPDATE", "instance": "cool-test", "data": [
        {"key": {"id": "message-1"}, "update": {"status": 3}},
        {"key": {"id": "unknown-message"}, "update": {"status": 4}},
    ]}
    assert channels.ingest_webhook(db, event) == {"created": 0, "updated": 1, "duplicates": 0, "ignored": 1}
    assert db.scalar(select(Message)).status == "delivered"


def test_receipts_do_not_change_incoming_or_mark_customer_read(db):
    channels.ingest_webhook(db, upsert())
    assert channels.ingest_webhook(db, receipt())["updated"] == 0
    assert db.scalar(select(Message)).status == "received"
    assert db.scalar(select(Conversation)).unread_count == 1


def test_media_records_type_and_never_claims_download(db):
    event = upsert(message={"imageMessage": {
        "caption": "套餐截图", "mimetype": "image/jpeg", "mediaKey": "do-not-persist",
        "url": "https://example.invalid/signed-media-url",
    }})
    event["apikey"] = "do-not-persist-api-key"
    assert channels.ingest_webhook(db, event)["created"] == 1
    message = db.scalar(select(Message))
    assert message.kind == "image"
    assert message.body == "[圖片，附件尚未下載] 套餐截图"
    assert message.metadata_json["media_downloaded"] is False
    assert "do-not-persist" not in json.dumps(message.metadata_json)
    assert "signed-media-url" not in json.dumps(message.metadata_json)


def test_lid_is_not_invented_phone_and_explicit_alternate_fills_phone(db):
    event = upsert()
    event["data"]["key"]["remoteJid"] = "123456789012345@lid"
    channels.ingest_webhook(db, event)
    contact = db.scalar(select(Contact))
    assert contact.wa_id == "123456789012345@lid"
    assert contact.phone == "lid:123456789012345"
    second = copy.deepcopy(event)
    second["data"]["key"].update(id="message-2", remoteJidAlt="85260000000@s.whatsapp.net")
    channels.ingest_webhook(db, second)
    db.refresh(contact)
    assert contact.phone == "+85260000000"
    assert contact.wa_id == "123456789012345@lid"
    assert db.scalar(select(func.count()).select_from(Contact)) == 1


@pytest.mark.parametrize("payload", [
    {"event": "messages.delete", "instance": "cool-test", "data": {"key": {"id": "x"}}},
    {"event": "messages.upsert", "instance": "wrong", "data": {}},
    {"event": "messages.upsert", "instance": "cool-test", "data": {"key": None}},
    {"event": "messages.update", "instance": "cool-test", "data": {"id": "unknown", "status": "READ"}},
])
def test_unsupported_events_and_bad_payloads_create_nothing(db, payload):
    assert channels.ingest_webhook(db, payload)["ignored"] == 1
    assert db.scalar(select(func.count()).select_from(Message)) == 0
    assert db.scalar(select(func.count()).select_from(Contact)) == 0


def test_group_protocol_and_stub_messages_are_ignored(db):
    group = upsert()
    group["data"]["key"]["remoteJid"] = "1234567890@g.us"
    assert channels.ingest_webhook(db, group)["ignored"] == 1
    assert channels.ingest_webhook(db, upsert(message={"protocolMessage": {"type": "REVOKE"}}))["ignored"] == 1
    assert channels.ingest_webhook(db, upsert(message={}))["ignored"] == 1
    # A subsequent real message with the stub's ID is still accepted.
    assert channels.ingest_webhook(db, upsert())["created"] == 1


def test_ambiguous_direction_is_rejected_instead_of_triggering_unread(db):
    event = upsert()
    event["data"]["key"]["fromMe"] = "false"
    assert channels.ingest_webhook(db, event)["ignored"] == 1
    assert db.scalar(select(func.count()).select_from(Message)) == 0


def test_duplicate_batch_and_nested_media_wrapper(db):
    event = upsert(message={"ephemeralMessage": {"message": {
        "audioMessage": {"mimetype": "audio/ogg"},
    }}})
    event["data"] = {"messages": [event["data"], copy.deepcopy(event["data"])]}
    result = channels.ingest_webhook(db, event)
    assert (result["created"], result["duplicates"]) == (1, 1)
    assert db.scalar(select(Message)).kind == "audio"
    assert db.scalar(select(Conversation)).unread_count == 1


def test_sending_disabled_even_when_configured():
    with pytest.raises(channels.ChannelError) as raised:
        channels.send_text("+85260000000", "不要真实发送", "test-request")
    assert raised.value.code == "send_disabled"
    assert raised.value.status_code == 409


def test_sending_requires_complete_configuration(channel_settings):
    channel_settings.allow_external_send = True
    channel_settings.evolution_api_key = ""
    with pytest.raises(channels.ChannelError) as raised:
        channels.send_text("+85260000000", "合成测试", "test-request")
    assert raised.value.code == "not_configured"


def test_sending_lid_requires_verified_phone(channel_settings):
    channel_settings.allow_external_send = True
    with pytest.raises(channels.ChannelError) as raised:
        channels.send_text("123456789012345@lid", "合成测试", "test-request")
    assert raised.value.code == "invalid_recipient"


def test_mock_send_returns_same_namespace_as_webhook(monkeypatch, channel_settings, db):
    channel_settings.allow_external_send = True
    requests = []
    def response(method, path, payload=None):
        requests.append((method, path, payload))
        return {"key": {"id": "message-1"}, "status": "PENDING"}
    monkeypatch.setattr(channels, "_request", response)
    result = channels.send_text("+85260000000", "合成测试", "test-request")
    channels.ingest_webhook(db, upsert(from_me=True))
    assert result["external_id"] == db.scalar(select(Message)).external_id
    assert result["status"] == "pending"
    assert requests == [("POST", "/message/sendText/cool-test", {"number": "85260000000", "text": "合成测试"})]


def test_send_timeout_is_ambiguous_and_not_retried(monkeypatch, channel_settings):
    channel_settings.allow_external_send = True
    calls = []
    class TimeoutOpener:
        def open(self, request, timeout):
            calls.append(request)
            raise URLError("synthetic timeout")
    monkeypatch.setattr(channels, "build_opener", lambda *args: TimeoutOpener())
    with pytest.raises(channels.ChannelError) as raised:
        channels.send_text("+85260000000", "合成测试", "test-request")
    assert raised.value.code == "delivery_unknown"
    assert len(calls) == 1
