"""Explicit evidence-use policies for the curated catalog.

These policies distinguish evidence eligibility from current inventory claims.
A dated listed price is usable for deterministic evaluation even when the
source reports out-of-stock, preorder, unknown, or does not report availability.
The availability observation remains attached and must be surfaced to callers.
"""

from __future__ import annotations

from enum import Enum

from app.contracts.components import ComponentType
from app.contracts.intake import PriceSnapshot


class PriceUsePolicy(str, Enum):
    LISTED_PRICE_EVIDENCE = "LISTED_PRICE_EVIDENCE"


PRICE_USE_POLICY = PriceUsePolicy.LISTED_PRICE_EVIDENCE


def price_is_eligible_for_evaluation(snapshot: PriceSnapshot) -> bool:
    """Return whether a price observation may contribute to evaluation.

    Eligibility requires a real, non-null listed VND price. Availability is
    intentionally not a feasibility/inventory gate in the current project
    policy; it remains a dated observation for display and explanation.
    """
    return snapshot.price_vnd is not None


def select_price_snapshot(
    snapshots: list[PriceSnapshot] | tuple[PriceSnapshot, ...],
    *,
    manufacturer: str,
    model: str,
    component_type: ComponentType,
) -> PriceSnapshot | None:
    """Select one deterministic dated price observation for a component.

    Priority is newest ``verified_at``; ties use lower VND price; remaining
    ties use listing URL ascending. Availability never participates in the
    selection or eligibility decision.
    """
    matches = [
        snapshot
        for snapshot in snapshots
        if snapshot.manufacturer == manufacturer
        and snapshot.exact_model == model
        and snapshot.component_type is component_type
        and price_is_eligible_for_evaluation(snapshot)
    ]
    if not matches:
        return None
    newest = max(snapshot.verified_at for snapshot in matches)
    newest_matches = [snapshot for snapshot in matches if snapshot.verified_at == newest]
    lowest_price = min(snapshot.price_vnd for snapshot in newest_matches)
    lowest_price_matches = [
        snapshot for snapshot in newest_matches if snapshot.price_vnd == lowest_price
    ]
    return min(lowest_price_matches, key=lambda snapshot: snapshot.listing_url)


def price_availability_disclaimer(snapshot: PriceSnapshot) -> str:
    """Return the deterministic disclaimer required for a price observation."""
    if snapshot.availability is None:
        state = "availability was not captured"
    else:
        state = f"availability was recorded as {snapshot.availability.value}"
    return f"Price is a dated listing snapshot; {state}. It is not a current inventory guarantee."
