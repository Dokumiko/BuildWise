"""Client-safe classifications for persisted scoring-catalog load failures.

The reconstruction adapter intentionally raises ``ValueError`` rather than
making unsafe assumptions. This module maps those stable failure categories to
messages that may cross an API boundary without exposing database internals,
source URLs, or raw exception text.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class CatalogLoadErrorCode(str, Enum):
    DATASET_UNAVAILABLE = "CATALOG_DATASET_UNAVAILABLE"
    COMPONENT_TYPES_MISSING = "CATALOG_COMPONENT_TYPES_MISSING"
    PRICE_SOURCE_METADATA_MISSING = "CATALOG_PRICE_SOURCE_METADATA_MISSING"
    PRICE_SOURCE_DATASET_AMBIGUOUS = "CATALOG_PRICE_SOURCE_DATASET_AMBIGUOUS"
    PRICE_EVIDENCE_MISSING = "CATALOG_PRICE_EVIDENCE_MISSING"
    BENCHMARK_EVIDENCE_MISSING = "CATALOG_BENCHMARK_EVIDENCE_MISSING"
    GPU_PROXY_EVIDENCE_INVALID = "CATALOG_GPU_PROXY_EVIDENCE_INVALID"
    EVIDENCE_INVALID = "CATALOG_EVIDENCE_INVALID"


class CatalogLoadFailure(BaseModel):
    """Stable public description of a rejected persisted catalog dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: CatalogLoadErrorCode
    message: str


def classify_catalog_load_error(error: ValueError) -> CatalogLoadFailure:
    """Classify a strict reconstruction failure without returning its raw text."""
    issue = str(error)
    if issue.startswith("no active canonical components"):
        return CatalogLoadFailure(
            code=CatalogLoadErrorCode.DATASET_UNAVAILABLE,
            message="The requested catalog dataset is unavailable.",
        )
    if issue.startswith("persisted catalog is missing required component types"):
        return CatalogLoadFailure(
            code=CatalogLoadErrorCode.COMPONENT_TYPES_MISSING,
            message="The requested catalog dataset lacks required component categories.",
        )
    if issue.startswith("persisted catalog is missing eligible price evidence"):
        return CatalogLoadFailure(
            code=CatalogLoadErrorCode.PRICE_EVIDENCE_MISSING,
            message="The requested catalog dataset lacks eligible price evidence for a canonical component.",
        )
    if issue.startswith("persisted price source lacks explicit catalog dataset metadata"):
        return CatalogLoadFailure(
            code=CatalogLoadErrorCode.PRICE_SOURCE_METADATA_MISSING,
            message="The requested catalog dataset has price evidence without dataset metadata.",
        )
    if issue.startswith("persisted price source has ambiguous catalog dataset membership"):
        return CatalogLoadFailure(
            code=CatalogLoadErrorCode.PRICE_SOURCE_DATASET_AMBIGUOUS,
            message="The requested catalog dataset has ambiguous price-source membership.",
        )
    if (
        "gpu_model_association" in issue
        or "GPU_MODEL_PROXY" in issue
        or "GPU model association" in issue
        or "GPU model proxy" in issue
    ):
        return CatalogLoadFailure(
            code=CatalogLoadErrorCode.GPU_PROXY_EVIDENCE_INVALID,
            message="The requested catalog dataset has invalid GPU model-proxy evidence.",
        )
    if "normalized benchmark evidence" in issue or "persisted benchmark context" in issue:
        return CatalogLoadFailure(
            code=CatalogLoadErrorCode.BENCHMARK_EVIDENCE_MISSING,
            message="The requested catalog dataset has incomplete benchmark evidence.",
        )
    if "GPU" in issue or "association" in issue:
        return CatalogLoadFailure(
            code=CatalogLoadErrorCode.GPU_PROXY_EVIDENCE_INVALID,
            message="The requested catalog dataset has invalid GPU model-proxy evidence.",
        )
    return CatalogLoadFailure(
        code=CatalogLoadErrorCode.EVIDENCE_INVALID,
        message="The requested catalog dataset has invalid persisted evidence.",
    )
