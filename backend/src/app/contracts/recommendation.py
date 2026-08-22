"""Typed deterministic requirements for constrained build recommendation.

These are manual/API boundary contracts. They contain preferences and limits,
not component facts; candidate components always come from the curated catalog.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.components import CaseFormFactor


class WorkloadProfile(str, Enum):
    GAMING = "gaming"
    PRODUCTIVITY = "productivity"
    MIXED = "mixed"


class BudgetMode(str, Enum):
    STRICT = "strict"
    APPROXIMATE = "approximate"


class RecommendationRequirements(BaseModel):
    """Supported deterministic filtering constraints for the first search slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    budget_vnd: int = Field(ge=3_000_000, le=200_000_000)
    budget_mode: BudgetMode
    primary_workload: WorkloadProfile
    minimum_ram_capacity_gb: int | None = Field(default=None, gt=0)
    minimum_storage_capacity_gb: int | None = Field(default=None, gt=0)
    case_form_factor: CaseFormFactor | None = None
    market: Literal["VN"] = "VN"
    currency: Literal["VND"] = "VND"
