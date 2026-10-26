"""Initial additive schema only. Later changes require explicit migrations."""

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .config import settings
from .models import Base, Source, User
from .security import hash_password


def initialize(engine):
    if len(settings.admin_password) < 16:
        raise RuntimeError("Set a private COOLDATASIM_ADMIN_PASSWORD of at least 16 characters")
    if engine.dialect.name == "postgresql":
        with engine.connect() as connection:
            # Serialize first startup of the API and worker, do not drop anything.
            connection.execute(text("SELECT pg_advisory_lock(771293005)"))
            connection.commit()
            try:
                Base.metadata.create_all(connection)
                connection.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version integer PRIMARY KEY)"))
                connection.execute(text("INSERT INTO schema_version VALUES (1) ON CONFLICT DO NOTHING"))
                connection.commit()
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(771293005)"))
                connection.commit()
    else:
        Base.metadata.create_all(engine)
    with Session(engine) as db:
        if not db.scalar(select(User).where(User.username == settings.admin_username)):
            db.add(User(username=settings.admin_username, display_name="管理員", role="admin",
                        password_hash=hash_password(settings.admin_password)))
        if not db.scalar(select(Source.id)):
            db.add(Source(name="Cool Data Sim 官方網站", url="https://www.cooldatasim.com/", max_pages=10))
        db.commit()
