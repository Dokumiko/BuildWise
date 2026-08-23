"""Commit one validated catalog-evaluation intake into the configured database.

Run from ``backend``:

    python -m app.scripts.import_evaluation_intake --path data/<intake>.json

The command has no network behavior and makes no schema changes. It commits
only after the complete typed intake persistence path succeeds; otherwise it
rolls back the request-scoped database session.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.services.catalog_evaluation_import import import_catalog_evaluation_intake


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and persist one explicit BuildWise catalog-evaluation intake."
    )
    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        help="Path to the catalog-evaluation intake JSON file.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the transactional operator command and return a process exit code."""
    args = _parser().parse_args(argv)
    session = SessionLocal()
    try:
        result = import_catalog_evaluation_intake(session, path=args.path)
        session.commit()
    except (OSError, ValueError, SQLAlchemyError) as error:
        session.rollback()
        print(f"Catalog evaluation intake import failed: {error}", file=sys.stderr)
        return 1
    except Exception:
        # Preserve an unexpected fault for an operator while still making the
        # transactional boundary explicit.
        session.rollback()
        raise
    finally:
        session.close()

    print(json.dumps(asdict(result), sort_keys=True, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by Python module execution.
    raise SystemExit(main())
