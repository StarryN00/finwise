from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.database import create_db_engine, create_session_factory


def test_database_helpers_create_overridable_sqlite_session():
    engine = create_db_engine("sqlite:///:memory:")
    session_factory = create_session_factory(engine)

    session = session_factory()
    try:
        assert isinstance(engine, Engine)
        assert isinstance(session, Session)
    finally:
        session.close()
