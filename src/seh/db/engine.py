"""Database engine factory and session management."""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.orm import Session, sessionmaker

from seh.config.settings import Settings
from seh.db.base import Base


def create_engine(settings: Settings) -> Engine:
    """Create a SQLAlchemy engine from settings.

    Args:
        settings: Application settings containing database URL.

    Returns:
        Configured SQLAlchemy engine.
    """
    connect_args: dict = {}

    # SQLite-specific configuration
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = sa_create_engine(
        settings.database_url,
        connect_args=connect_args,
        echo=settings.log_level == "DEBUG",
        pool_pre_ping=True,
    )

    return engine


def create_tables(engine: Engine) -> None:
    """Create all database tables.

    Args:
        engine: SQLAlchemy engine.
    """
    # Import models to ensure they're registered with Base
    from seh.db import models as _  # noqa: F401

    Base.metadata.create_all(bind=engine)


def drop_tables(engine: Engine) -> None:
    """Drop all database tables.

    Args:
        engine: SQLAlchemy engine.
    """
    Base.metadata.drop_all(bind=engine)


@contextmanager
def get_session(engine: Engine) -> Generator[Session, None, None]:
    """Get a database session context manager.

    Args:
        engine: SQLAlchemy engine.

    Yields:
        Database session that will be automatically committed on success
        or rolled back on failure.
    """
    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
