"""Combine deterministic engine results and persist historical analysis records.

Persistence is append-only: each completed analysis creates a new
analysis_results row. The persisted status is derived from returned findings,
not maintained independently.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Iterable

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.contracts.components import ComponentRecord, CpuMotherboardSupportRecord
from app.db.models import AnalysisResult, AnalysisStatus
from app.services.compatibility import (
    CompatibilityAnalysis,
    CompatibilityBuild,
    FindingSeverity,
    analyze_compatibility,
)
from app.services.power import PowerAnalysis, PowerBuild, PowerPolicy, analyze_power


class DeterministicAnalysis(BaseModel):
    """Combined pure-engine result in the JSON shapes used by analysis_results."""

    model_config = ConfigDict(extra="forbid")

    engine_version: str
    status: AnalysisStatus
    summary: dict[str, object]
    findings: list[dict[str, object]]
    assumptions: list[str]

    @property
    def feasible(self) -> bool:
        return self.status is not AnalysisStatus.INCOMPATIBLE


def _combined_status(
    compatibility: CompatibilityAnalysis, power: PowerAnalysis
) -> AnalysisStatus:
    all_findings = [*compatibility.findings, *power.findings]
    if any(finding.severity is FindingSeverity.ERROR for finding in all_findings):
        return AnalysisStatus.INCOMPATIBLE
    if any(finding.severity is FindingSeverity.WARNING for finding in all_findings):
        return AnalysisStatus.COMPATIBLE_WITH_WARNINGS
    return AnalysisStatus.COMPATIBLE


def _decimal_or_none(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def analyze_deterministic_build(
    records: Iterable[ComponentRecord],
    *,
    cpu_motherboard_support: Iterable[CpuMotherboardSupportRecord] = (),
    power_policy: PowerPolicy | None = None,
) -> DeterministicAnalysis:
    """Run completed compatibility and power analysis on canonical records."""
    records = tuple(records)
    support_rows = tuple(cpu_motherboard_support)
    compatibility = analyze_compatibility(
        CompatibilityBuild.from_records(records, cpu_motherboard_support=support_rows)
    )
    power = analyze_power(
        PowerBuild.from_records(records),
        **({"policy": power_policy} if power_policy is not None else {}),
    )
    status = _combined_status(compatibility, power)
    findings = [
        {"domain": "COMPATIBILITY", **finding.model_dump(mode="json")}
        for finding in compatibility.findings
    ] + [
        {"domain": "POWER", **finding.model_dump(mode="json")}
        for finding in power.findings
    ]
    summary: dict[str, object] = {
        "compatibility_status": compatibility.status.value,
        "power_status": power.status.value,
        "estimated_system_draw_w": _decimal_or_none(power.estimated_system_draw_w),
        "minimum_required_psu_capacity_w": _decimal_or_none(
            power.minimum_required_psu_capacity_w
        ),
        "recommended_psu_capacity_w": _decimal_or_none(
            power.recommended_psu_capacity_w
        ),
        "selected_psu_capacity_w": _decimal_or_none(power.selected_psu_capacity_w),
        "headroom_w": _decimal_or_none(power.headroom_w),
        "power_policy_version": power.policy_version,
    }
    return DeterministicAnalysis(
        engine_version=(
            f"compatibility-{compatibility.engine_version}"
            f"+power-{power.engine_version}"
        ),
        status=status,
        summary=summary,
        findings=findings,
        assumptions=power.assumptions,
    )


def persist_analysis_result(
    session: Session,
    *,
    build_id: uuid.UUID,
    analysis: DeterministicAnalysis,
) -> AnalysisResult:
    """Append one completed deterministic analysis to a persisted build.

    The caller owns transaction commit/rollback. This function intentionally
    never updates a prior result, preserving historical evidence.
    """
    result = AnalysisResult(
        build_id=build_id,
        engine_version=analysis.engine_version,
        status=analysis.status,
        summary=analysis.summary,
        findings=analysis.findings,
        assumptions=analysis.assumptions,
    )
    session.add(result)
    session.flush()
    return result
