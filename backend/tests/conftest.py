from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """Provide a DB session that always rolls back."""
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    connection = engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()
        engine.dispose()


def clear_catalog_tables(session: Session) -> None:
    """Remove catalog/build rows in FK-safe order inside the current transaction."""
    statements = [
        "DELETE FROM analysis_results",
        "DELETE FROM build_items",
        "DELETE FROM builds",
        "DELETE FROM component_prices",
        "DELETE FROM benchmark_records",
        "DELETE FROM component_sources",
        "DELETE FROM cpu_motherboard_support",
        "DELETE FROM components",
        "DELETE FROM data_sources",
    ]
    for statement in statements:
        session.execute(text(statement))
    session.flush()
