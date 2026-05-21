from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.database import create_db_engine, create_session_factory, normalize_database_url


def test_normalize_database_url_uses_psycopg_for_bare_postgresql_url():
    assert (
        normalize_database_url("postgresql://user:pass@localhost/db")
        == "postgresql+psycopg://user:pass@localhost/db"
    )


def test_normalize_database_url_keeps_explicit_psycopg_url():
    assert (
        normalize_database_url("postgresql+psycopg://user:pass@localhost/db")
        == "postgresql+psycopg://user:pass@localhost/db"
    )


def test_normalize_database_url_keeps_sqlite_url():
    assert normalize_database_url("sqlite:///./finwise_accounting.db") == "sqlite:///./finwise_accounting.db"


def test_database_helpers_create_overridable_sqlite_session():
    engine = create_db_engine("sqlite:///:memory:")
    session_factory = create_session_factory(engine)

    session = session_factory()
    try:
        assert isinstance(engine, Engine)
        assert isinstance(session, Session)
    finally:
        session.close()
