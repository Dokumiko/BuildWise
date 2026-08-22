from datetime import timedelta
from pathlib import Path

from app.contracts.components import AvailabilityStatus
from app.services.catalog_intake import load_validated_intake
from app.services.catalog_policies import (
    PRICE_USE_POLICY,
    PriceUsePolicy,
    price_availability_disclaimer,
    price_is_eligible_for_evaluation,
    select_price_snapshot,
)


V02_INTAKE = (
    Path(__file__).parents[1] / "data" / "vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json"
)


def test_dated_listed_prices_are_eligible_regardless_of_availability() -> None:
    intake = load_validated_intake(V02_INTAKE)

    assert PRICE_USE_POLICY is PriceUsePolicy.LISTED_PRICE_EVIDENCE
    assert all(price_is_eligible_for_evaluation(snapshot) for snapshot in intake.price_snapshots)
    assert {
        snapshot.availability for snapshot in intake.price_snapshots
    } == {
        None,
        AvailabilityStatus.IN_STOCK,
        AvailabilityStatus.OUT_OF_STOCK,
        AvailabilityStatus.PREORDER,
        AvailabilityStatus.UNKNOWN,
    }


def test_price_selection_is_newest_then_lowest_then_listing_url() -> None:
    snapshot = load_validated_intake(V02_INTAKE).price_snapshots[0]
    older_lower = snapshot.model_copy(
        update={
            "price_vnd": 1,
            "listing_url": "https://a.example/old",
            "verified_at": snapshot.verified_at - timedelta(days=1),
        }
    )
    newest_high = snapshot.model_copy(update={"price_vnd": 700, "listing_url": "https://z.example/new"})
    newest_low_z = snapshot.model_copy(update={"price_vnd": 600, "listing_url": "https://z.example/new-low"})
    newest_low_a = snapshot.model_copy(update={"price_vnd": 600, "listing_url": "https://a.example/new-low"})

    selected = select_price_snapshot(
        (older_lower, newest_high, newest_low_z, newest_low_a),
        manufacturer=snapshot.manufacturer,
        model=snapshot.exact_model,
        component_type=snapshot.component_type,
    )

    assert selected is newest_low_a


def test_missing_price_is_not_evaluation_eligible_and_disclaimer_preserves_state() -> None:
    snapshot = load_validated_intake(V02_INTAKE).price_snapshots[0]

    assert not price_is_eligible_for_evaluation(snapshot.model_copy(update={"price_vnd": None}))
    assert "PREORDER" in price_availability_disclaimer(snapshot)
    assert "not a current inventory guarantee" in price_availability_disclaimer(snapshot)
    assert "not captured" in price_availability_disclaimer(
        snapshot.model_copy(update={"availability": None})
    )
