"""Report whether one validated intake can support deterministic search.

Run from ``backend`` before importing an evaluation catalog:

    python -m app.scripts.check_catalog_readiness --path data/<intake>.json

The command performs no database or network operation. It reports the existing
readiness gate's structured findings as JSON and uses exit status ``2`` for a
valid intake that is not ready for constrained search.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from app.services.catalog_intake import load_validated_intake
from app.services.catalog_readiness import assess_catalog_readiness


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assess one explicit BuildWise catalog-evaluation intake for scoring/search readiness."
    )
    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        help="Path to the catalog-evaluation intake JSON file.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Write a structured readiness report and return an operator exit code."""
    args = _parser().parse_args(argv)
    try:
        report = assess_catalog_readiness(load_validated_intake(args.path))
    except (OSError, ValueError) as error:
        print(f"Catalog readiness check failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
    return 0 if report.constrained_search_ready else 2


if __name__ == "__main__":  # pragma: no cover - exercised by Python module execution.
    raise SystemExit(main())
