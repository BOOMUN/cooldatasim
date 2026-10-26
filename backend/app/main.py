from contextlib import asynccontextmanager
from datetime import timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from .config import settings
from .database import engine as default_engine
from .migrate import initialize
from .models import AuditLog, Contact, Conversation, Document, Job, LoginSession, Message, Product, Source, User, utcnow
from .security import hash_password, token_hash, verify_password


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class ContactInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    phone: str = Field(min_length=3, max_length=80)
    language: str = Field(default="zh-HK", max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=5000)
    attributes: dict[str, str] = Field(default_factory=dict)

    @field_validator("display_name", "phone")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("不可空白")
        return value.strip()

    @field_validator("tags")
    @classmethod
    def tags_bounded(cls, value):
        if any(len(item) > 80 for item in value):
            raise ValueError("標籤過長")
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @field_validator("attributes")
    @classmethod
    def attributes_bounded(cls, value):
        if len(value) > 30 or any(len(k) > 80 or len(v) > 500 for k, v in value.items()):
            raise ValueError("自訂欄位過長")
        return value


class ConversationInput(BaseModel):
    contact_id: int


class ConversationPatch(BaseModel):
    mode: str | None = None
    assigned_user_id: int | None = None


class SendInput(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    internal: bool = False
    idempotency_key: str = Field(min_length=8, max_length=100)


class TextInput(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


class SourceInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=1, max_length=2000)
    max_pages: int = Field(default=10, ge=1, le=50)


class DocumentInput(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    url: str = Field(default="", max_length=2000)
    category: str = Field(default="其他", max_length=80)
    content: str = Field(min_length=10, max_length=100000)

    @field_validator("url")
    @classmethod
    def source_link(cls, value):
        if value and (urlsplit(value).scheme != "https" or not urlsplit(value).hostname or urlsplit(value).username):
            raise ValueError("來源連結必須為 HTTPS 或留空")
        return value


class QuestionInput(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class ProductPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    sku: str | None = Field(default=None, max_length=160)
    country: str | None = Field(default=None, max_length=80)
    card_type: str | None = Field(default=None, max_length=40)
    days: int | None = Field(default=None, ge=1, le=3650)
    data_allowance: str | None = Field(default=None, max_length=80)
    price: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    original_price: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str | None = Field(default=None, max_length=12)


class UserInput(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=160)
    role: str
    password: str = Field(min_length=16, max_length=200)


def serialize(record, exclude=()):
    result = {}
    for column in record.__table__.columns:
        if column.key in exclude:
            continue
        value = getattr(record, column.key)
        if hasattr(value, "isoformat"):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            value = value.isoformat()
        result[column.key] = value
    return result


def create_app(database_engine=None):
    engine = database_engine or default_engine
    factory = sessionmaker(engine, expire_on_commit=False)
    login_attempts = {}
    rate_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        initialize(engine)
        yield

    app = FastAPI(title="Cool Data Sim 客服後台", lifespan=lifespan)
    app.state.session_factory = factory

    def db_dep():
        with factory() as db:
            yield db

    @app.middleware("http")
    async def safe_request(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "請從同一網站操作"}, status_code=403)
            length = request.headers.get("content-length", "0")
            if not length.isdecimal() or int(length) > 2_000_000:
                return JSONResponse({"detail": "請求過大"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def current(request: Request, db=Depends(db_dep)):
        session = db.get(LoginSession, token_hash(request.cookies.get("cds_session", "")))
        if not session:
            raise HTTPException(401, "請先登入")
        expiry = session.expires_at.replace(tzinfo=timezone.utc) if session.expires_at.tzinfo is None else session.expires_at
        if expiry <= utcnow():
            raise HTTPException(401, "登入已過期")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if not hmac.compare_digest(session.csrf_token, request.headers.get("X-CSRF-Token", "")):
                raise HTTPException(403, "請重新登入後操作")
        user = db.get(User, session.user_id)
        if not user:
            raise HTTPException(401, "帳號無效")
        return user, session

    def manager(auth=Depends(current)):
        if auth[0].role not in {"admin", "knowledge_manager"}:
            raise HTTPException(403, "需要知識管理權限")
        return auth

    def admin(auth=Depends(current)):
        if auth[0].role != "admin":
            raise HTTPException(403, "需要管理員權限")
        return auth

    def record_audit(db, user, action, target):
        db.add(AuditLog(actor_id=user.id, action=action, target=str(target)))

    def must_get(db, cls, identity):
        value = db.get(cls, identity)
        if value is None:
            raise HTTPException(404, "資料不存在")
        return value

    def must_conversation(db, identity, user):
        value = must_get(db, Conversation, identity)
        if value.sandbox and user.role != "admin":
            raise HTTPException(403, "本地演練僅限管理員")
        return value

    def conversation_data(db, row, detail=False):
        data = serialize(row)
        data["contact"] = serialize(db.get(Contact, row.contact_id))
        latest = db.scalar(select(Message).where(Message.conversation_id == row.id).order_by(Message.id.desc()).limit(1))
        data["preview"] = latest.body[:100] if latest else "尚無訊息"
        if detail:
            data["messages"] = []
            recent = list(db.scalars(select(Message).where(Message.conversation_id == row.id).order_by(Message.id.desc()).limit(501)))
            data["messages_has_more"] = len(recent) > 500
            for item in reversed(recent[:500]):
                value = serialize(item, {"request_hash", "idempotency_key"})
                value["metadata"] = value.pop("metadata_json")
                data["messages"].append(value)
        return data

    @app.exception_handler(IntegrityError)
    async def duplicate_handler(request, exc):
        return JSONResponse({"detail": "資料已存在或操作衝突，請重新整理"}, status_code=409)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, exc):
        labels = {"username": "帳號", "password": "密碼", "display_name": "名稱", "phone": "電話",
                  "body": "訊息", "title": "標題", "content": "內容", "url": "網址", "name": "名稱",
                  "question": "問題", "max_pages": "採集頁數", "price": "價格", "days": "天數",
                  "idempotency_key": "操作編號", "role": "角色", "contact_id": "客戶編號"}
        messages = []
        for error in exc.errors()[:4]:
            field = labels.get(str(error["loc"][-1]), "輸入欄位")
            kind, context = error["type"], error.get("ctx", {})
            if kind == "missing":
                message = f"請填寫{field}"
            elif kind == "string_too_short":
                message = f"{field}至少需要 {context.get('min_length')} 個字元"
            elif kind == "string_too_long":
                message = f"{field}不可超過 {context.get('max_length')} 個字元"
            elif kind in {"greater_than_equal", "less_than_equal", "int_parsing", "float_parsing", "finite_number"}:
                message = f"{field}的數值或範圍不正確"
            elif kind == "json_invalid":
                message = "資料格式不正確，請重新整理後再試"
            else:
                message = f"請檢查{field}的格式與內容"
            messages.append(message)
        return JSONResponse({"detail": "；".join(messages)}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request, exc):
        defaults = {404: "找不到頁面或資料", 405: "此操作方式不適用", 413: "請求資料過大"}
        message = exc.detail
        if isinstance(message, str) and message in {"Not Found", "Method Not Allowed", "Request Entity Too Large"}:
            message = defaults.get(exc.status_code, "請求未能完成")
        return JSONResponse({"detail": message}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request, exc):
        return JSONResponse({"detail": "服務暫時無法完成此操作，請稍後再試或聯絡管理員"}, status_code=500)

    @app.get("/api/health")
    def health():
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "application": "cooldatasim", "schema_version": 1}

    @app.post("/api/auth/login")
    def login(payload: LoginInput, request: Request, response: Response, db=Depends(db_dep)):
        identity = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with rate_lock:
            attempts = [v for v in login_attempts.get(identity, []) if now - v < 300]
            if len(attempts) >= 15:
                raise HTTPException(429, "嘗試次數過多，請稍後再試")
            login_attempts[identity] = attempts + [now]
        user = db.scalar(select(User).where(User.username == payload.username))
        if not user or not verify_password(payload.password, user.password_hash):
            raise HTTPException(401, "帳號或密碼不正確")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        db.add(LoginSession(id=token_hash(token), user_id=user.id, csrf_token=csrf, expires_at=utcnow() + timedelta(hours=8)))
        db.commit()
        response.set_cookie("cds_session", token, httponly=True, secure=settings.secure_cookies,
                            samesite="strict", max_age=28800, path="/")
        return {"user": serialize(user, {"password_hash"}), "csrf_token": csrf}

    @app.get("/api/auth/me")
    def me(auth=Depends(current)):
        return {"user": serialize(auth[0], {"password_hash"}), "csrf_token": auth[1].csrf_token}

    @app.post("/api/auth/logout")
    def logout(response: Response, auth=Depends(current), db=Depends(db_dep)):
        db.delete(auth[1])
        db.commit()
        response.delete_cookie("cds_session", path="/")
        return {"ok": True}

    @app.get("/api/users")
    def users(auth=Depends(current), db=Depends(db_dep)):
        return [serialize(u, {"password_hash"}) for u in db.scalars(select(User).order_by(User.id))]

    @app.post("/api/users", status_code=201)
    def add_user(payload: UserInput, auth=Depends(admin), db=Depends(db_dep)):
        if payload.role not in {"admin", "agent", "knowledge_manager"}:
            raise HTTPException(422, "角色無效")
        user = User(**payload.model_dump(exclude={"password"}), password_hash=hash_password(payload.password))
        db.add(user)
        record_audit(db, auth[0], "user.create", payload.username)
        db.commit()
        return serialize(user, {"password_hash"})

    @app.get("/api/contacts")
    def contacts(q: str = "", auth=Depends(current), db=Depends(db_dep)):
        query = select(Contact)
        if q:
            query = query.where(or_(Contact.display_name.ilike(f"%{q[:100]}%"), Contact.phone.ilike(f"%{q[:100]}%")))
        return [serialize(c) for c in db.scalars(query.order_by(Contact.id.desc()).limit(500))]

    @app.post("/api/contacts", status_code=201)
    def add_contact(payload: ContactInput, auth=Depends(current), db=Depends(db_dep)):
        contact = Contact(**payload.model_dump())
        db.add(contact)
        db.commit()
        return serialize(contact)

    @app.patch("/api/contacts/{identity}")
    def update_contact(identity: int, payload: ContactInput, auth=Depends(current), db=Depends(db_dep)):
        contact = must_get(db, Contact, identity)
        for key, value in payload.model_dump().items():
            setattr(contact, key, value)
        record_audit(db, auth[0], "contact.update", identity)
        db.commit()
        return serialize(contact)

    @app.get("/api/conversations")
    def conversations(q: str = "", view: str = "all", auth=Depends(current), db=Depends(db_dep)):
        query = select(Conversation).join(Contact)
        if auth[0].role != "admin":
            query = query.where(Conversation.sandbox.is_(False))
        if q:
            query = query.where(or_(Contact.display_name.ilike(f"%{q[:100]}%"), Contact.phone.ilike(f"%{q[:100]}%")))
        if view == "mine":
            query = query.where(Conversation.assigned_user_id == auth[0].id)
        elif view == "unassigned":
            query = query.where(Conversation.assigned_user_id.is_(None))
        elif view == "unread":
            query = query.where(Conversation.unread_count > 0)
        elif view != "all":
            raise HTTPException(422, "篩選無效")
        return [conversation_data(db, c) for c in db.scalars(query.order_by(Conversation.updated_at.desc()).limit(200))]

    @app.post("/api/conversations", status_code=201)
    def add_conversation(payload: ConversationInput, auth=Depends(current), db=Depends(db_dep)):
        must_get(db, Contact, payload.contact_id)
        existing = db.scalar(select(Conversation).where(Conversation.contact_id == payload.contact_id, Conversation.sandbox.is_(False)))
        if existing:
            return conversation_data(db, existing)
        c = Conversation(contact_id=payload.contact_id)
        db.add(c)
        db.commit()
        return conversation_data(db, c)

    @app.get("/api/conversations/{identity}")
    def conversation(identity: int, auth=Depends(current), db=Depends(db_dep)):
        return conversation_data(db, must_conversation(db, identity, auth[0]), True)

    @app.patch("/api/conversations/{identity}")
    def update_conversation(identity: int, payload: ConversationPatch, auth=Depends(current), db=Depends(db_dep)):
        c = must_conversation(db, identity, auth[0])
        changes = payload.model_dump(exclude_unset=True)
        if "mode" in changes and changes["mode"] not in {"manual", "ai_draft"}:
            raise HTTPException(422, "首版僅提供人工或 AI 建議模式")
        if changes.get("assigned_user_id") is not None:
            must_get(db, User, changes["assigned_user_id"])
        for key, value in changes.items():
            setattr(c, key, value)
        c.updated_at = utcnow()
        record_audit(db, auth[0], "conversation.update", identity)
        db.commit()
        return conversation_data(db, c)

    @app.post("/api/conversations/{identity}/read")
    def mark_read(identity: int, auth=Depends(current), db=Depends(db_dep)):
        c = must_conversation(db, identity, auth[0])
        c.unread_count = 0
        db.commit()
        return {"ok": True, "whatsapp_read_receipt_sent": False}

    @app.post("/api/conversations/{identity}/messages")
    def send(identity: int, payload: SendInput, auth=Depends(current), db=Depends(db_dep)):
        c = must_conversation(db, identity, auth[0])
        if not payload.body.strip():
            raise HTTPException(422, "訊息不可空白")
        digest = hashlib.sha256(json.dumps([identity, payload.body, payload.internal]).encode()).hexdigest()
        key = f"user:{auth[0].id}:{payload.idempotency_key}"
        old = db.scalar(select(Message).where(Message.idempotency_key == key))
        if old:
            if old.request_hash != digest:
                raise HTTPException(409, "同一操作編號不可重用於不同訊息")
            return serialize(old, {"request_hash"})
        if not payload.internal and not c.sandbox:
            # Deliberate first-release gate: adapters may exist, live send is not approved.
            raise HTTPException(409, "WhatsApp 真實發送尚未聯調；可使用內部備註或本地演練")
        message = Message(conversation_id=identity, body=payload.body.strip(),
                          direction="internal" if payload.internal else "outgoing", sender_type="agent",
                          status="note" if payload.internal else "simulated", idempotency_key=key,
                          request_hash=digest, metadata_json={"sandbox": c.sandbox, "actor": auth[0].display_name})
        db.add(message)
        c.updated_at = utcnow()
        db.commit()
        return serialize(message, {"request_hash"})

    @app.post("/api/sandbox", status_code=201)
    def sandbox(auth=Depends(admin), db=Depends(db_dep)):
        contact = Contact(display_name="本地演練客戶", phone=f"sandbox-{secrets.token_hex(4)}", tags=["演練資料"], notes="此會話不連接 WhatsApp")
        db.add(contact)
        db.flush()
        c = Conversation(contact_id=contact.id, sandbox=True, assigned_user_id=auth[0].id, mode="ai_draft")
        db.add(c)
        db.commit()
        return conversation_data(db, c, True)

    @app.post("/api/conversations/{identity}/simulate")
    def simulate(identity: int, payload: TextInput, auth=Depends(admin), db=Depends(db_dep)):
        c = must_get(db, Conversation, identity)
        if not c.sandbox:
            raise HTTPException(403, "只可在演練會話模擬訊息")
        db.add(Message(conversation_id=identity, body=payload.body, direction="incoming", sender_type="customer", status="simulated"))
        c.unread_count += 1
        c.updated_at = utcnow()
        db.commit()
        return conversation_data(db, c, True)

    @app.get("/api/sources")
    def sources(auth=Depends(current), db=Depends(db_dep)):
        return [serialize(s) for s in db.scalars(select(Source).order_by(Source.id))]

    @app.post("/api/sources", status_code=201)
    def add_source(payload: SourceInput, auth=Depends(manager), db=Depends(db_dep)):
        from .knowledge import validate_source_url
        try:
            url = validate_source_url(payload.url)
        except ValueError:
            raise HTTPException(422, "網址必須是允許的公開網站") from None
        source = Source(name=payload.name, url=url, max_pages=payload.max_pages)
        db.add(source)
        db.commit()
        return serialize(source)

    @app.post("/api/sources/{identity}/sync")
    def sync_source(identity: int, auth=Depends(manager), db=Depends(db_dep)):
        source = db.scalar(select(Source).where(Source.id == identity).with_for_update())
        if not source:
            raise HTTPException(404, "來源不存在")
        active = db.scalar(select(Job).where(Job.source_id == identity, Job.status.in_(["queued", "running"])))
        if active:
            return serialize(active)
        job = Job(source_id=identity)
        db.add(job)
        source.status = "queued"
        db.commit()
        return serialize(job)

    @app.get("/api/jobs")
    def jobs(auth=Depends(current), db=Depends(db_dep)):
        return [serialize(j) for j in db.scalars(select(Job).order_by(Job.id.desc()).limit(100))]

    @app.get("/api/documents")
    def documents(q: str = "", status: str = "", auth=Depends(current), db=Depends(db_dep)):
        query = select(Document)
        if q:
            query = query.where(Document.title.ilike(f"%{q[:100]}%"))
        if status:
            query = query.where(Document.status == status)
        return [serialize(d) for d in db.scalars(query.order_by(Document.updated_at.desc()).limit(300))]

    @app.get("/api/documents/{identity}")
    def document(identity: int, auth=Depends(current), db=Depends(db_dep)):
        return serialize(must_get(db, Document, identity))

    @app.post("/api/documents", status_code=201)
    def add_document(payload: DocumentInput, auth=Depends(manager), db=Depends(db_dep)):
        doc = Document(**payload.model_dump())
        db.add(doc)
        db.commit()
        return serialize(doc)

    @app.patch("/api/documents/{identity}")
    def update_document(identity: int, payload: DocumentInput, auth=Depends(manager), db=Depends(db_dep)):
        doc = db.scalar(select(Document).where(Document.id == identity).with_for_update())
        if not doc:
            raise HTTPException(404, "資料不存在")
        for key, value in payload.model_dump().items():
            setattr(doc, key, value)
        doc.status = "draft"
        doc.revision += 1
        doc.updated_at = utcnow()
        record_audit(db, auth[0], "document.edit", identity)
        db.commit()
        return serialize(doc)

    @app.post("/api/documents/{identity}/publish")
    def publish(identity: int, auth=Depends(manager), db=Depends(db_dep)):
        from .knowledge import publish_document
        doc = must_get(db, Document, identity)
        try:
            publish_document(db, doc)
        except (ValueError, RuntimeError) as exc:
            db.rollback()
            raise HTTPException(503, "知識索引失敗；未宣告發布成功，請檢查模型設定") from None
        record_audit(db, auth[0], "document.publish", identity)
        db.commit()
        return serialize(doc)

    @app.post("/api/documents/{identity}/withdraw")
    def withdraw(identity: int, auth=Depends(manager), db=Depends(db_dep)):
        from .knowledge import withdraw_document
        doc = must_get(db, Document, identity)
        withdraw_document(db, doc)
        record_audit(db, auth[0], "document.withdraw", identity)
        db.commit()
        return serialize(doc)

    @app.get("/api/products")
    def products(q: str = "", auth=Depends(current), db=Depends(db_dep)):
        query = select(Product)
        if q:
            query = query.where(or_(Product.name.ilike(f"%{q[:100]}%"), Product.country.ilike(f"%{q[:100]}%")))
        return [serialize(p) for p in db.scalars(query.order_by(Product.id.desc()).limit(500))]

    @app.patch("/api/products/{identity}")
    def update_product(identity: int, payload: ProductPatch, auth=Depends(manager), db=Depends(db_dep)):
        product = db.scalar(select(Product).where(Product.id == identity).with_for_update())
        if not product:
            raise HTTPException(404, "資料不存在")
        for key, value in payload.model_dump(exclude_unset=True).items():
            if key == "name" and value is None:
                raise HTTPException(422, "商品名稱不可空白")
            setattr(product, key, value)
        product.status = "draft"
        product.verified_at = None
        db.commit()
        return serialize(product)

    @app.post("/api/products/{identity}/publish")
    def publish_product(identity: int, auth=Depends(manager), db=Depends(db_dep)):
        product = db.scalar(select(Product).where(Product.id == identity).with_for_update())
        if not product:
            raise HTTPException(404, "資料不存在")
        if product.price is None or not product.currency or not product.url.startswith("https://"):
            raise HTTPException(422, "需要核實價格、幣種及 HTTPS 來源網址")
        product.status = "published"
        product.verified_at = utcnow()
        record_audit(db, auth[0], "product.publish", identity)
        db.commit()
        return serialize(product)

    def generate(db, question, history=None, session_id=None):
        from .ai import generate_answer
        try:
            return generate_answer(db, question, history=history, session_id=session_id)
        except (ValueError, RuntimeError) as exc:
            # Never leak provider URLs, headers, keys or raw HTTP error bodies.
            raise HTTPException(503, "AI 服務尚未設定或暫不可用；請檢查對話模型與檢索設定") from None

    @app.post("/api/ai/preview")
    def preview(payload: QuestionInput, auth=Depends(current), db=Depends(db_dep)):
        return generate(db, payload.question, session_id=f"preview:{auth[1].id}")

    @app.post("/api/conversations/{identity}/suggest")
    def suggest(identity: int, auth=Depends(current), db=Depends(db_dep)):
        c = must_conversation(db, identity, auth[0])
        if c.mode != "ai_draft":
            raise HTTPException(409, "目前為人工接管，請先切換為 AI 建議模式")
        messages = list(db.scalars(select(Message).where(Message.conversation_id == identity, Message.direction != "internal").order_by(Message.id.desc()).limit(20)))[::-1]
        incoming = [m for m in messages if m.direction == "incoming"]
        if not incoming:
            raise HTTPException(422, "尚無客戶問題")
        history = [{"role": "user" if m.direction == "incoming" else "assistant", "content": m.body} for m in messages]
        return generate(db, incoming[-1].body, history, session_id=f"conversation:{identity}")

    @app.get("/api/integrations")
    def integrations(auth=Depends(current)):
        chat = {"configured": bool(settings.active_chat_base_url and settings.active_chat_model),
                "provider": settings.active_chat_provider, "model": settings.active_chat_model,
                "reasoning_effort": settings.active_chat_reasoning_effort,
                "display_name": "DeepSeek V4.1 Flash" if settings.active_chat_model == "deepseek-v4.1-flash" else settings.active_chat_model}
        return {
            "chat": chat,
            "qwen": {**chat, "alias_of": "chat"},
            "embedding": {"configured": bool(settings.embedding_base_url), "model": settings.embedding_model, "dimensions": 1024},
            "reranker": {"configured": bool(settings.reranker_base_url), "model": settings.reranker_model},
            "whatsapp": {"configured": bool(settings.evolution_base_url and settings.evolution_api_key and settings.evolution_instance),
                         "enabled": False, "provider": "evolution", "instance": settings.evolution_instance},
        }

    @app.post("/api/ai/probe")
    def probe(auth=Depends(admin)):
        from .ai import probe_models
        return probe_models()

    @app.get("/api/whatsapp/status")
    def whatsapp_status(auth=Depends(admin)):
        from .channels import channel_status
        try:
            return channel_status()
        except (ValueError, RuntimeError):
            raise HTTPException(503, "通道服務不可用") from None

    @app.post("/api/webhooks/evolution")
    async def webhook(request: Request, db=Depends(db_dep)):
        from .channels import ingest_webhook, verify_webhook
        raw = await request.body()
        if len(raw) > 2_000_000:
            raise HTTPException(413, "請求過大")
        if not verify_webhook(raw, request.headers):
            raise HTTPException(401, "Webhook 驗證失敗")
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise HTTPException(422, "Webhook 格式無效") from None
        result = ingest_webhook(db, payload)
        db.commit()
        return result

    @app.get("/api/status")
    def status(auth=Depends(current), db=Depends(db_dep)):
        return {"database": "ready", "app_version": "0.1.0", "delivery": "disabled_pending_validation",
                "documents": db.scalar(select(func.count(Document.id))),
                "products": db.scalar(select(func.count(Product.id))),
                "jobs_pending": db.scalar(select(func.count(Job.id)).where(Job.status.in_(["queued", "running"]))) }

    static = Path(__file__).resolve().parents[2] / "static"
    if static.is_dir():
        if (static / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/logo.png")
        def logo():
            return FileResponse(static / "logo.png")

        @app.get("/")
        def index():
            return FileResponse(static / "index.html")

    return app


app = create_app()
