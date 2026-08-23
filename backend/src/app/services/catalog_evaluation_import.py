"""Transactional application boundary for a catalog-evaluation intake file.

The lower-level persistence service deliberately does not commit so callers can
compose it safely. This service validates one explicit file and prepares its
result for an operator-controlled transaction; the CLI owns commit/rollback.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.catalog_intake import load_validated_intake
from app.services.catalog_intake_persistence import (
    IntakePersistenceResult,
    persist_catalog_evaluation_intake,
)


@dataclass(frozen=True)
class CatalogEvaluationImportResult:
    """Dataset identity and counts prepared by one validated intake import."""

    dataset_version: str
    persistence: IntakePersistenceResult


def import_catalog_evaluation_intake(
    session: Session,
    *,
    path: Path,
) -> CatalogEvaluationImportResult:
    """Validate and persist one explicit evaluation intake without committing.

    The caller controls the surrounding transaction. No raw component facts,
    price snapshots, benchmark values, or GPU associations are accepted other
    than through the typed intake file and existing canonical persistence path.
    """
    intake = load_validated_intake(path)
    persistence = persist_catalog_evaluation_intake(session, intake)
    return CatalogEvaluationImportResult(
        dataset_version=intake.dataset_version,
        persistence=persistence,
    )
