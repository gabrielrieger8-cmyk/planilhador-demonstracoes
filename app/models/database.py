"""SQLAlchemy engine, session factory e Base declarativa."""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

engine = None
SessionLocal = None


class Base(DeclarativeBase):
    pass


def init_db(database_url: str) -> None:
    """Inicializa engine e session factory.

    Para SQLite: desabilita check_same_thread e habilita WAL + foreign keys.
    Para PostgreSQL: usa pool_pre_ping.
    """
    global engine, SessionLocal

    is_sqlite = database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    pool_pre_ping = not is_sqlite

    engine = create_engine(
        database_url,
        pool_pre_ping=pool_pre_ping,
        connect_args=connect_args,
    )

    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    SessionLocal = sessionmaker(bind=engine)

    # Auto-create tables (para dev/SQLite — em produção usar Alembic)
    if is_sqlite:
        Base.metadata.create_all(bind=engine)


def get_session():
    """Generator que fornece uma sessão e garante fechamento."""
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
