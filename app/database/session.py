from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionFactory = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        db_url = settings.database_url
        if "sqlite" in db_url:
            # Ensure directory exists for sqlite DB
            if db_url.startswith("sqlite:///"):
                db_path = db_url.replace("sqlite:///", "")
                if not db_path.startswith(":memory:"):
                    path_obj = Path(db_path)
                    path_obj.parent.mkdir(parents=True, exist_ok=True)
            _engine = create_engine(
                db_url,
                connect_args={"check_same_thread": False},
                pool_pre_ping=True,
            )
        else:
            _engine = create_engine(db_url, pool_pre_ping=True)
    return _engine


def get_session_factory():
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return _SessionFactory


def SessionLocal() -> Session:
    factory = get_session_factory()
    return factory()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app.database import models as _  # noqa: F401
    Base.metadata.create_all(bind=get_engine())
