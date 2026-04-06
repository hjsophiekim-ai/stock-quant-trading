from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base


def build_engine(db_url: str, echo: bool = False) -> Engine:
    connect_args: dict[str, object] = {}
    if db_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(db_url, echo=echo, future=True, connect_args=connect_args)


def build_session_factory(db_url: str, echo: bool = False) -> sessionmaker[Session]:
    engine = build_engine(db_url=db_url, echo=echo)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(db_url: str, echo: bool = False) -> None:
    engine = build_engine(db_url=db_url, echo=echo)
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
