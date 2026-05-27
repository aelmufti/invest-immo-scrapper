"""Gestion du moteur SQLAlchemy et de la session.

Conçu pour SQLite mais migration vers PostgreSQL = simple changement de l'URL.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from core.settings import get_settings

from .models import Base, Parametres

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Renvoie le moteur SQLAlchemy (singleton)."""
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        connect_args: dict = {}
        if settings.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(
            settings.database_url,
            echo=False,
            future=True,
            connect_args=connect_args,
        )

        # PRAGMA pour SQLite : WAL = meilleur en accès concurrent (API + UI + scheduler)
        if settings.database_url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragma(dbapi_conn, _):  # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL;")
                cur.execute("PRAGMA foreign_keys=ON;")
                cur.execute("PRAGMA synchronous=NORMAL;")
                cur.close()

        _SessionLocal = sessionmaker(
            bind=_engine, autoflush=False, autocommit=False, future=True
        )
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Contexte transactionnel."""
    SessionLocal = get_sessionmaker()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Crée les tables (idempotent) et insère le singleton Parametres si absent."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    with session_scope() as s:
        if s.get(Parametres, 1) is None:
            s.add(Parametres(id=1))
