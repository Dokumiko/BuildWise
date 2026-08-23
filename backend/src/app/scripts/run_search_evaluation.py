"""Run reproducible deterministic search evaluation for caller-supplied scenarios.

Run from ``backend``:

    python -m app.scripts.run_search_evaluation \
      --dataset-version vn-pc-am5-ddr5-v0.2 \
      --scenarios path/to/scenarios.json

The scenario file is supplied and labeled by the evaluation caller; this
command deliberately does not manufacture a thesis scenario dataset. It reads
one persisted dataset through the strict reconstruction boundary, writes no
database rows, and prints a machine-readable report including catalog, search,
and scoring configuration versions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.services.evaluation import EvaluationScenario, SearchEvaluationConfig
from app.services.persisted_evaluation import (
    evaluate_persisted_scoring_sensitivity,
    evaluate_persisted_search_scenarios,
)
from app.services.scoring import DEFAULT_SCORING_CONFIG, ScoringConfig

REPORT_SCHEMA_VERSION = "search-evaluation-report-0.1"
_SCENARIOS = TypeAdapter(tuple[EvaluationScenario, ...])
_SCORING_CONFIGS = TypeAdapter(tuple[ScoringConfig, ...])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate one persisted BuildWise catalog against caller-supplied scenarios."
    )
    parser.add_argument(
        "--dataset-version",
        required=True,
        help="Explicit persisted catalog dataset version to reconstruct.",
    )
    parser.add_argument(
        "--scenarios",
        type=Path,
        required=True,
        help="JSON array of EvaluationScenario objects supplied by the caller.",
    )
    parser.add_argument(
        "--scenario-set-version",
        required=True,
        help="Caller-defined non-empty version label for the supplied scenario set.",
    )
    parser.add_argument(
        "--evaluation-config",
        type=Path,
        help="Optional JSON SearchEvaluationConfig object; defaults to K=3,5,10,20.",
    )
    parser.add_argument(
        "--scoring-configs",
        type=Path,
        help=(
            "Optional JSON array of ScoringConfig objects. When supplied, the report "
            "also includes scoring-sensitivity stability against the first config."
        ),
    )
    return parser


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_scenarios(path: Path) -> tuple[tuple[EvaluationScenario, ...], str]:
    # Parse and hash the same bytes so the report fingerprint always identifies
    # the exact scenario payload used for this evaluation run.
    raw_payload = path.read_bytes()
    scenarios = _SCENARIOS.validate_python(json.loads(raw_payload))
    if not scenarios:
        raise ValueError("scenarios must not be empty")
    return scenarios, hashlib.sha256(raw_payload).hexdigest()


def _load_evaluation_config(path: Path | None) -> SearchEvaluationConfig:
    return (
        SearchEvaluationConfig.model_validate(_load_json(path))
        if path is not None
        else SearchEvaluationConfig()
    )


def _load_scoring_configs(path: Path | None) -> tuple[ScoringConfig, ...] | None:
    if path is None:
        return None
    configs = _SCORING_CONFIGS.validate_python(_load_json(path))
    if not configs:
        raise ValueError("scoring_configs must not be empty")
    return configs


def main(argv: Sequence[str] | None = None) -> int:
    """Run read-only persisted evaluation and print a reproducible JSON report."""
    args = _parser().parse_args(argv)
    try:
        if not args.dataset_version.strip() or args.dataset_version != args.dataset_version.strip():
            raise ValueError("dataset_version must be non-empty and contain no surrounding whitespace")
        if (
            not args.scenario_set_version.strip()
            or args.scenario_set_version != args.scenario_set_version.strip()
        ):
            raise ValueError(
                "scenario_set_version must be non-empty and contain no surrounding whitespace"
            )
        scenarios, scenario_file_sha256 = _load_scenarios(args.scenarios)
        evaluation_config = _load_evaluation_config(args.evaluation_config)
        scoring_configs = _load_scoring_configs(args.scoring_configs)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as error:
        print(f"Search evaluation input failed: {error}", file=sys.stderr)
        return 1

    session = SessionLocal()
    try:
        search_evaluation = evaluate_persisted_search_scenarios(
            session,
            scenarios,
            dataset_version=args.dataset_version,
            evaluation_config=evaluation_config,
        )
        sensitivity = (
            evaluate_persisted_scoring_sensitivity(
                session,
                scenarios,
                dataset_version=args.dataset_version,
                scoring_configs=scoring_configs,
            )
            if scoring_configs is not None
            else None
        )
    except (ValueError, SQLAlchemyError) as error:
        print(f"Search evaluation failed: {error}", file=sys.stderr)
        return 1
    finally:
        session.close()

    print(
        json.dumps(
            {
                "report_schema_version": REPORT_SCHEMA_VERSION,
                "dataset_version": args.dataset_version,
                "scenario_set_version": args.scenario_set_version,
                "scenario_file_sha256": scenario_file_sha256,
                "evaluation_config": evaluation_config.model_dump(mode="json"),
                "search_scoring_config": DEFAULT_SCORING_CONFIG.model_dump(mode="json"),
                "scoring_configs": (
                    [item.model_dump(mode="json") for item in scoring_configs]
                    if scoring_configs is not None
                    else None
                ),
                "search_evaluation": search_evaluation.model_dump(mode="json"),
                "scoring_sensitivity": (
                    sensitivity.model_dump(mode="json") if sensitivity is not None else None
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by Python module execution.
    raise SystemExit(main())
