"""Import the owner-verified BuildWise Excel catalog snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.services.catalog_snapshot_import import import_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import every component from an owner-verified BuildWise workbook."
    )
    parser.add_argument(
        "--path",
        required=True,
        type=Path,
        help="Path to the .xlsx workbook snapshot.",
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        result = import_snapshot(session, path=args.path)
        session.commit()
        print(json.dumps(result, sort_keys=True, default=str))
        return 0
    except (OSError, ValueError, SQLAlchemyError) as error:
        session.rollback()
        print(f"catalog snapshot import failed: {error}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
