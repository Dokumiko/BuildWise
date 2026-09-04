"""Machine-readable catalog-dataset metadata stored in existing DDL text/JSONB fields.

No relational schema is added for the current reconstruction slice. Metadata is
written only by the validated catalog-evaluation importer and is parsed
strictly by the database catalog adapter. Ambiguous price-source membership is
rejected rather than guessed.
"""

from __future__ import annotations

import re

_DATASET_PATTERN = re.compile(r"\[buildwise_catalog_dataset=([^\]\r\n]+)\]")
CANONICAL_COMPONENT_ROLE = "CANONICAL"
RAW_ONLY_COMPONENT_ROLE = "RAW_ONLY"
_COMPONENT_ROLE_PATTERN = re.compile(
    r"\[buildwise_catalog_component_role="
    r"([^;\]\r\n]+);dataset=([^\]\r\n]+)\]"
)


def dataset_marker(dataset_version: str) -> str:
    return f"[buildwise_catalog_dataset={dataset_version}]"


def component_role_marker(*, dataset_version: str, role: str) -> str:
    return f"[buildwise_catalog_component_role={role};dataset={dataset_version}]"


def append_dataset_marker(value: str | None, dataset_version: str) -> str:
    """Append one dataset marker once while preserving human-readable text."""
    existing = value or ""
    marker = dataset_marker(dataset_version)
    if marker in existing:
        return existing
    return f"{existing}\n{marker}".strip()


def remove_dataset_marker(value: str | None, dataset_version: str) -> str | None:
    """Remove one explicit dataset marker while preserving other provenance."""
    if value is None:
        return None
    cleaned = value.replace(dataset_marker(dataset_version), "")
    cleaned = re.sub(r"\n{2,}", "\n", cleaned).strip()
    return cleaned or None


def merge_dataset_markers(existing: str | None, incoming: str | None) -> str | None:
    """Preserve all explicit dataset markers when a source URL is reused."""
    if existing is None and incoming is None:
        return None
    merged = existing or incoming or ""
    for version in sorted(dataset_versions(incoming)):
        merged = append_dataset_marker(merged, version)
    return merged


def append_component_metadata(
    value: str | None,
    *,
    dataset_version: str,
    role: str,
) -> str:
    """Attach a dataset-specific canonical/raw-only role to provenance notes."""
    existing = append_dataset_marker(value, dataset_version)
    marker = component_role_marker(dataset_version=dataset_version, role=role)
    if marker in existing:
        return existing
    return f"{existing}\n{marker}".strip()


def replace_component_role_metadata(
    value: str | None,
    *,
    dataset_version: str,
    role: str,
) -> str:
    """Set one dataset role without retaining a stale role from a prior import.

    A component can only be one of CANONICAL or RAW_ONLY within one dataset.
    Other datasets' markers are deliberately preserved.
    """
    existing = append_dataset_marker(value, dataset_version)
    marker_pattern = re.compile(
        r"(?:^|\n)\[buildwise_catalog_component_role=[^;\]\r\n]+;dataset="
        + re.escape(dataset_version)
        + r"\]"
    )
    cleaned = marker_pattern.sub("", existing).strip()
    marker = component_role_marker(dataset_version=dataset_version, role=role)
    return f"{cleaned}\n{marker}".strip()


def component_role_memberships(value: str | None) -> frozenset[tuple[str, str]]:
    """Return explicit ``(dataset_version, role)`` provenance memberships."""
    return frozenset(
        (dataset_version, role)
        for role, dataset_version in _COMPONENT_ROLE_PATTERN.findall(value or "")
    )


def merge_component_metadata(existing: str | None, incoming: str | None) -> str | None:
    """Preserve all dataset-specific roles when provenance is reused."""
    if existing is None and incoming is None:
        return None
    merged = incoming or existing or ""
    for version in sorted(dataset_versions(existing)):
        merged = append_dataset_marker(merged, version)
    for dataset_version, role in sorted(component_role_memberships(existing)):
        marker = component_role_marker(dataset_version=dataset_version, role=role)
        if marker not in merged:
            merged = f"{merged}\n{marker}".strip()
    return merged


def dataset_versions(value: str | None) -> frozenset[str]:
    """Return explicit dataset memberships from a stored text field."""
    return frozenset(match.group(1) for match in _DATASET_PATTERN.finditer(value or ""))



def is_dataset_component_for_dataset(value: str | None, dataset_version: str) -> bool:
    """Return whether a component carries either explicit role for a dataset."""
    return (
        dataset_version in dataset_versions(value)
        and any(version == dataset_version for version, _role in component_role_memberships(value))
    )

def is_canonical_component_for_dataset(value: str | None, dataset_version: str) -> bool:
    return (
        dataset_version in dataset_versions(value)
        and (dataset_version, CANONICAL_COMPONENT_ROLE)
        in component_role_memberships(value)
    )
