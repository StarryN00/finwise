from collections.abc import Generator
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _connect_args(url: str) -> dict[str, bool]:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


settings = get_settings()


def normalize_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def create_db_engine(database_url: Optional[str] = None) -> Engine:
    url = normalize_database_url(database_url or settings.database_url)
    return create_engine(url, connect_args=_connect_args(url))


def create_session_factory(bind: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=bind, autoflush=False, autocommit=False)


engine = create_db_engine()
SessionLocal = create_session_factory(engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
