from pathlib import Path

from app.contracts.components import AvailabilityStatus
from app.services.catalog_intake import load_validated_intake
from app.services.catalog_policies import (
    PRICE_USE_POLICY,
    PriceUsePolicy,
    price_availability_disclaimer,
    price_is_eligible_for_evaluation,
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


def test_missing_price_is_not_evaluation_eligible_and_disclaimer_preserves_state() -> None:
    snapshot = load_validated_intake(V02_INTAKE).price_snapshots[0]

    assert not price_is_eligible_for_evaluation(snapshot.model_copy(update={"price_vnd": None}))
    assert "PREORDER" in price_availability_disclaimer(snapshot)
    assert "not a current inventory guarantee" in price_availability_disclaimer(snapshot)
    assert "not captured" in price_availability_disclaimer(
        snapshot.model_copy(update={"availability": None})
    )
