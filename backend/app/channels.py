"""Restricted Evolution adapter; no pairing, history import or automatic AI send.

Only the application owns database commits and durable outbound idempotency.
Provider protocol details must still be tested against an authorized instance.
"""

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .models import Contact, Conversation, Message, utcnow


class ChannelError(RuntimeError):
    def __init__(self, message: str, code: str, status_code: int = 503):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_STATUS = {
    "ERROR": "failed", "PENDING": "pending", "SERVER_ACK": "sent",
    "DELIVERY_ACK": "delivered", "READ": "read", "PLAYED": "played",
    "SENT": "sent", "DELIVERED": "delivered",
}
_NUMERIC_STATUS = {0: "failed", 1: "pending", 2: "sent", 3: "delivered", 4: "read", 5: "played"}
_STATUS_RANK = {"pending": 0, "sending": 0, "sent": 1, "delivered": 2, "read": 3, "played": 4}
_MEDIA = {
    "imageMessage": ("image", "圖片"), "videoMessage": ("video", "影片"),
    "audioMessage": ("audio", "語音"), "documentMessage": ("document", "檔案"),
    "stickerMessage": ("sticker", "貼圖"),
}


def _configured() -> bool:
    return all((settings.evolution_base_url.strip(), settings.evolution_api_key.strip(),
                settings.evolution_instance.strip()))


def _external_id(instance: str, message_id: str) -> str:
    # Fixed length, collision-resistant namespace; raw IDs live in filtered metadata.
    identity = json.dumps(["evolution", instance, message_id], ensure_ascii=False).encode("utf-8")
    return "evolution:" + hashlib.sha256(identity).hexdigest()


def _status(value) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return _NUMERIC_STATUS.get(value)
    if isinstance(value, str):
        return _STATUS.get(value.upper())
    return None


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    base = settings.evolution_base_url.rstrip("/")
    parsed = urlsplit(base)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ChannelError("WhatsApp 服務地址設定無效。", "invalid_configuration", 409)
    request = Request(base + path, method=method, headers={
        "apikey": settings.evolution_api_key, "Accept": "application/json",
        "Content-Type": "application/json",
    }, data=None if payload is None else json.dumps(payload).encode("utf-8"))
    try:
        # No redirects (which could expose credentials), no retries after a send.
        with build_opener(_NoRedirect()).open(request, timeout=12) as response:
            body = response.read(1_048_577)
        if len(body) > 1_048_576:
            raise ValueError("response too large")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise ValueError("unexpected response shape")
        return result
    except HTTPError as exc:
        if method == "POST" and (exc.code >= 500 or exc.code == 408):
            raise ChannelError("發送結果尚未確認，請核實通道紀錄，勿自動重發。", "delivery_unknown") from None
        raise ChannelError("WhatsApp 服務拒絕請求，請檢查服務與實例設定。", "upstream_rejected") from None
    except (URLError, TimeoutError, OSError, ValueError, UnicodeError):
        code = "delivery_unknown" if method == "POST" else "upstream_unavailable"
        message = ("發送結果尚未確認，請核實通道紀錄，勿自動重發。" if method == "POST"
                   else "WhatsApp 服務無法使用或傳回格式不相容。")
        raise ChannelError(message, code) from None


def channel_status() -> dict:
    result = {
        "provider": "evolution", "configured": _configured(),
        "enabled": settings.allow_external_send, "instance": settings.evolution_instance,
        "state": "not_configured", "verified": False,
        "capabilities": {
            "text_receive": "implemented_unverified", "phone_message_sync": "implemented_unverified",
            "text_send": "disabled" if not settings.allow_external_send else "implemented_unverified",
            "delivery_receipts": "implemented_unverified", "media_receive": "metadata_only",
            "media_download": "not_implemented", "media_send": "not_implemented",
            "edit_revoke": "not_implemented", "history_sync": "not_implemented",
            "quote_reply": "not_implemented", "reaction_sync": "not_implemented",
            "read_state_sync": "not_implemented",
            "pairing": "not_implemented", "groups_calls": "not_implemented",
        },
    }
    if not result["configured"]:
        return result
    try:
        data = _request("GET", "/instance/connectionState/" + quote(settings.evolution_instance, safe=""))
        instance = data.get("instance")
        state = instance.get("state") if isinstance(instance, dict) else data.get("state")
        name = instance.get("instanceName") if isinstance(instance, dict) else instance
        if name and name != settings.evolution_instance:
            raise ChannelError("通道傳回了其他實例的狀態。", "instance_mismatch")
        valid_states = {"open", "close", "connecting", "connected", "disconnected"}
        result["state"] = state if isinstance(state, str) and state in valid_states else "unknown"
        result["status_checked"] = True
        # A status response never proves message synchronization was validated.
    except ChannelError as exc:
        result.update(state="unavailable", error=str(exc), error_code=exc.code)
    return result


def send_text(to: str, body: str, idempotency_key: str) -> dict:
    """One attempt only. Caller must persist idempotency before calling this function."""
    if not settings.allow_external_send:
        raise ChannelError("真實 WhatsApp 外發尚未授權，目前已停用。", "send_disabled", 409)
    if not _configured():
        raise ChannelError("WhatsApp 通道尚未設定完整。", "not_configured", 409)
    if not isinstance(to, str) or not re.fullmatch(r"\+?[1-9][0-9]{6,14}(?:@s\.whatsapp\.net)?", to):
        raise ChannelError("需要已核實且包含國際區號的電話號碼；不將 LID 當成電話號碼。", "invalid_recipient", 422)
    if not isinstance(body, str) or not body.strip() or len(body) > 10000:
        raise ChannelError("訊息正文為空或超過長度限制。", "invalid_body", 422)
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 160:
        raise ChannelError("發送必須包含有效冪等鍵。", "invalid_idempotency_key", 422)
    result = _request("POST", "/message/sendText/" + quote(settings.evolution_instance, safe=""), {
        "number": to.removesuffix("@s.whatsapp.net").removeprefix("+"), "text": body,
    })
    key = result.get("key")
    provider_id = key.get("id") if isinstance(key, dict) else None
    if not isinstance(provider_id, str) or not provider_id or len(provider_id) > 512:
        raise ChannelError("通道未傳回訊息編號，發送結果待核實，勿自動重發。", "delivery_unknown")
    return {"external_id": _external_id(settings.evolution_instance, provider_id),
            "provider_id": provider_id, "instance": settings.evolution_instance,
            "status": _status(result.get("status")) or "pending"}


def verify_webhook(raw_body: bytes, headers: Mapping) -> bool:
    """Verify the configured shared-secret header, not a provider body signature.

    Evolution must be configured to send this custom header. A reverse proxy must
    preserve it; TLS is required when traffic leaves the local trusted network.
    """
    if not settings.webhook_secret or not isinstance(raw_body, bytes):
        return False
    supplied = next((value for key, value in headers.items()
                     if str(key).lower() == "x-cooldatasim-webhook-secret"), "")
    if not isinstance(supplied, str) or not supplied:
        return False
    return hmac.compare_digest(hashlib.sha256(supplied.encode("utf-8")).digest(),
                               hashlib.sha256(settings.webhook_secret.encode("utf-8")).digest())


def _direct_jid(value) -> tuple[str, str | None] | None:
    if not isinstance(value, str) or len(value) > 160:
        return None
    match = re.fullmatch(r"([0-9]{1,40})(?::[0-9]+)?@(s\.whatsapp\.net|c\.us|lid)", value)
    if not match:
        return None
    local, domain = match.groups()
    if domain == "lid":
        return local + "@lid", None
    if not 7 <= len(local) <= 15:
        return None
    return local + "@s.whatsapp.net", "+" + local


def _content(item: dict) -> tuple[str, str, dict] | None:
    message = item.get("message")
    if not isinstance(message, dict) or not message:
        return None  # Ignore stubs; a later real upsert can then be ingested.
    for _ in range(4):
        wrapped = next((message[name].get("message") for name in (
            "ephemeralMessage", "viewOnceMessage", "viewOnceMessageV2", "documentWithCaptionMessage"
        ) if isinstance(message.get(name), dict)), None)
        if not isinstance(wrapped, dict):
            break
        message = wrapped
    text = message.get("conversation")
    if not isinstance(text, str):
        extended = message.get("extendedTextMessage")
        text = extended.get("text") if isinstance(extended, dict) else None
    if isinstance(text, str) and text:
        return "text", text[:65536], {}
    for name, (kind, label) in _MEDIA.items():
        media = message.get(name)
        if isinstance(media, dict):
            caption = media.get("caption")
            body = f"[{label}，附件尚未下載]"
            if isinstance(caption, str) and caption:
                body += " " + caption[:4000]
            metadata = {"media_downloaded": False}
            for source, target in (("mimetype", "mime_type"), ("fileName", "file_name")):
                value = media.get(source)
                if isinstance(value, str):
                    metadata[target] = value[:300]
            return kind, body, metadata
    # Do not turn edits, deletion commands or key exchange into chat messages.
    if any(name in message for name in ("protocolMessage", "senderKeyDistributionMessage", "reactionMessage")):
        return None
    if isinstance(message.get("locationMessage"), dict):
        return "location", "[位置訊息，首版尚未提供地圖展示]", {}
    if any(name in message for name in ("contactMessage", "contactsArrayMessage")):
        return "contact", "[聯絡人名片，首版尚未提供名片檢視]", {}
    return "unsupported", "[暫不支援的訊息類型，內容尚未解析]", {"parsed": False}


def _created_at(value) -> datetime:
    try:
        if isinstance(value, bool):
            return utcnow()
        if isinstance(value, dict):
            value = value.get("low")
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        if timestamp < 0:
            return utcnow()
        return datetime.fromtimestamp(timestamp, timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return utcnow()


def _upgrade_status(db: Session, external_id: str, value) -> bool:
    desired = _status(value)
    if desired is None:
        return False
    message = db.scalar(select(Message).where(Message.external_id == external_id).with_for_update())
    if not message or message.direction != "outgoing" or message.status == desired:
        return False
    # Failure is a separate terminal outcome, not a higher delivery receipt.
    if desired == "failed":
        allowed = message.status in {"pending", "sending", "sent"}
    else:
        allowed = message.status != "failed" and _STATUS_RANK.get(desired, -1) > _STATUS_RANK.get(message.status, -1)
    if not allowed:
        return False
    message.status = desired
    db.flush()
    return True


def _new_message(db: Session, instance: str, item: dict, external_id: str) -> bool:
    key = item.get("key", {})
    identity = _direct_jid(key.get("remoteJid"))
    content = _content(item)
    if identity is None or content is None or type(key.get("fromMe")) is not bool:
        return False
    jid, phone = identity
    alternate = _direct_jid(key.get("remoteJidAlt"))
    if phone is None and alternate:
        phone = alternate[1]
    phone = phone or "lid:" + jid.split("@", 1)[0]
    known_jids = [jid] + ([alternate[0]] if alternate else [])
    filters = [Contact.wa_id.in_(known_jids), Contact.phone == phone]
    if phone.startswith("+"):
        filters.append(Contact.phone == phone[1:])
    contact = db.scalar(select(Contact).where(or_(*filters)).order_by(Contact.id).with_for_update())
    if contact is None:
        name = item.get("pushName") if not key["fromMe"] else None
        contact = Contact(display_name=name[:160] if isinstance(name, str) and name else phone,
                          phone=phone, wa_id=jid)
        db.add(contact)
        db.flush()
    elif contact.wa_id is None:
        contact.wa_id = jid
    # An explicit PN alternate can fill a previously unresolved LID identity.
    elif contact.phone.startswith("lid:") and phone.startswith("+"):
        phone_owner = db.scalar(select(Contact).where(Contact.phone.in_([phone, phone[1:]])))
        if phone_owner is None or phone_owner.id == contact.id:
            contact.phone = phone
    conversation = db.scalar(select(Conversation).where(
        Conversation.contact_id == contact.id, Conversation.sandbox.is_(False),
        Conversation.status == "open",
    ).order_by(Conversation.id.desc()).with_for_update())
    if conversation is None:
        conversation = Conversation(contact_id=contact.id, mode="manual", unread_count=0, sandbox=False)
        db.add(conversation)
        db.flush()
    kind, body, extra = content
    from_me = key["fromMe"]
    metadata = {"provider": "evolution", "instance": instance, "provider_id": key["id"],
                "remote_jid": key["remoteJid"], "ai_triggered": False, **extra}
    if alternate:
        metadata["remote_jid_alt"] = key["remoteJidAlt"]
    db.add(Message(conversation_id=conversation.id, body=body, kind=kind,
                   direction="outgoing" if from_me else "incoming",
                   sender_type="phone" if from_me else "customer",
                   status=(_status(item.get("status")) or "pending") if from_me else "received",
                   external_id=external_id, metadata_json=metadata,
                   created_at=_created_at(item.get("messageTimestamp"))))
    db.flush()  # Uniqueness must succeed before changing unread counters.
    values = {"updated_at": utcnow()}
    if not from_me:
        values["unread_count"] = Conversation.unread_count + 1
    db.execute(update(Conversation).where(Conversation.id == conversation.id).values(**values))
    return True


def ingest_webhook(db: Session, payload: dict) -> dict:
    """Ingest already-authenticated events; caller commits. Never calls AI or sends."""
    counts = {"created": 0, "updated": 0, "duplicates": 0, "ignored": 0}
    if not isinstance(payload, dict) or not settings.evolution_instance:
        return {**counts, "ignored": 1, "reason": "not_configured_or_invalid"}
    instance = payload.get("instance")
    if not isinstance(instance, str) or instance != settings.evolution_instance:
        return {**counts, "ignored": 1, "reason": "instance_mismatch"}
    event = payload.get("event")
    event = event.lower().replace("_", ".") if isinstance(event, str) else ""
    if event not in {"messages.upsert", "messages.update", "messages.status"}:
        return {**counts, "ignored": 1, "reason": "unsupported_event"}
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("messages"), list):
        items = data["messages"]
    else:
        items = data if isinstance(data, list) else [data]
    for item in items:
        if not isinstance(item, dict):
            counts["ignored"] += 1
            continue
        key = item.get("key") if isinstance(item.get("key"), dict) else {}
        provider_id = key.get("id") if event == "messages.upsert" else (item.get("keyId") or key.get("id") or item.get("id"))
        if not isinstance(provider_id, str) or not provider_id or len(provider_id) > 512:
            counts["ignored"] += 1
            continue
        external_id = _external_id(instance, provider_id)
        if event != "messages.upsert":
            status = item.get("status")
            if status is None and isinstance(item.get("update"), dict):
                status = item["update"].get("status")
            counts["updated" if _upgrade_status(db, external_id, status) else "ignored"] += 1
            continue
        if db.scalar(select(Message.id).where(Message.external_id == external_id)) is not None:
            counts["duplicates"] += 1
            counts["updated"] += int(_upgrade_status(db, external_id, item.get("status")))
            continue
        # Savepoints isolate concurrent duplicate callbacks without rolling back
        # earlier valid items in this webhook batch.
        for attempt in range(2):
            try:
                with db.begin_nested():
                    created = _new_message(db, instance, item, external_id)
                counts["created" if created else "ignored"] += 1
                break
            except IntegrityError:
                if db.scalar(select(Message.id).where(Message.external_id == external_id)) is not None:
                    counts["duplicates"] += 1
                    break
                if attempt:
                    raise
    return counts
