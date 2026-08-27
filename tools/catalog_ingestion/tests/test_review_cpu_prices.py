from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.catalog_ingestion.review_cpu_prices import (
    PRICE_BASIS,
    RESOLUTION_STATUS,
    ReviewedPriceFile,
    apply_reviewed_price_resolutions,
    attach_price_resolutions,
    render_review_queue,
)

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "runs" / "cpu-evidence-2026-08-27"
CANDIDATES = EVIDENCE / "cpu-candidates.json"
REVIEW = EVIDENCE / "cpu-price-review.json"


def _price(model: str, url: str, price_text: str, requested_url: str | None = None) -> dict:
    return {
        "component_type": "CPU",
        "manufacturer": "AMD",
        "exact_model": model,
        "price_source": {
            "listing_url": url,
            "retailer_name": "HACOM",
            "price_text": price_text,
            "fetched_at": "2026-08-27T00:00:00+00:00",
        },
        "source_evidence": {
            "requested_url": requested_url or url,
            "final_url": requested_url or url,
            "status": 200,
        },
        "review_status": "PENDING_TECHNICAL_AND_BENCHMARK_JOIN",
    }


def _review(*records: dict) -> dict:
    return {
        "review_schema_version": "0.1",
        "policy": "Use verified retail CPU-only prices.",
        "reviewed_at": "2026-08-28",
        "records": list(records),
    }


def test_duplicate_category_and_detail_observations_collapse_to_one_resolution() -> None:
    prices = [
        _price("Athlon 3000G", "https://hacom.vn/cpu-amd-athlon-3300g", "1.299.000", "https://hacom.vn/cpu-amd"),
        _price("Athlon 3000G", "https://hacom.vn/cpu-amd-athlon-3300g", "999.000", "https://hacom.vn/cpu-amd-athlon-3300g"),
    ]
    original = copy.deepcopy(prices)
    resolutions = apply_reviewed_price_resolutions(
        prices,
        _review({
            "manufacturer": "AMD",
            "exact_model": "Athlon 3000G",
            "listing_url": "https://hacom.vn/cpu-amd-athlon-3300g",
            "variant": "RETAIL_BOXED",
            "selected_price_vnd": 1299000,
            "rationale": "Retail CPU price, not the bundle.",
        }),
    )
    assert prices == original
    assert len(resolutions) == 1
    assert resolutions[0]["raw_observation_count"] == 2
    assert resolutions[0]["observed_price_texts"] == ["1.299.000", "999.000"]
    assert resolutions[0]["selected_price_vnd"] == 1299000
    assert resolutions[0]["selected_price_found_in_crawler_observations"] is True
    assert resolutions[0]["price_basis"] == PRICE_BASIS
    assert resolutions[0]["review_status"] == RESOLUTION_STATUS


def test_tray_and_boxed_listings_remain_separate() -> None:
    prices = [
        _price("Ryzen 5 7500F", "https://hacom.vn/cpu-amd-ryzen-5-7500f-cpua0313", "3.699.000"),
        _price(
            "Ryzen 5 7500F",
            "https://hacom.vn/cpu-amd-ryzen-ryzen-5-7500f-3.7-ghz-upto-5.0ghz-38mb-6-cores-12-threads-65w-socket-am5",
            "5.199.000",
        ),
    ]
    resolutions = apply_reviewed_price_resolutions(
        prices,
        _review(
            {
                "manufacturer": "AMD",
                "exact_model": "Ryzen 5 7500F",
                "listing_url": "https://hacom.vn/cpu-amd-ryzen-5-7500f-cpua0313",
                "variant": "TRAY_NO_BOX",
                "selected_price_vnd": 4199000,
                "rationale": "Genuine no-box/tray retail price.",
            },
            {
                "manufacturer": "AMD",
                "exact_model": "Ryzen 5 7500F",
                "listing_url": "https://hacom.vn/cpu-amd-ryzen-ryzen-5-7500f-3.7-ghz-upto-5.0ghz-38mb-6-cores-12-threads-65w-socket-am5",
                "variant": "RETAIL_BOXED",
                "selected_price_vnd": 5199000,
                "rationale": "Separate boxed listing.",
            },
        ),
    )
    assert [item["variant"] for item in resolutions] == ["TRAY_NO_BOX", "RETAIL_BOXED"]
    assert [item["selected_price_vnd"] for item in resolutions] == [4199000, 5199000]
    assert resolutions[0]["listing_url"] != resolutions[1]["listing_url"]
    assert resolutions[0]["selected_price_found_in_crawler_observations"] is False
    assert resolutions[1]["selected_price_found_in_crawler_observations"] is True


def test_selected_price_is_not_inferred_from_raw_observations() -> None:
    prices = [_price("Ryzen 5 5600X", "https://hacom.vn/cpu-amd-ryzen-5-5600x", "3.699.000")]
    with pytest.raises(Exception, match="selected_price_vnd"):
        apply_reviewed_price_resolutions(
            prices,
            _review({
                "manufacturer": "AMD",
                "exact_model": "Ryzen 5 5600X",
                "listing_url": "https://hacom.vn/cpu-amd-ryzen-5-5600x",
                "variant": "RETAIL_BOXED",
                "rationale": "missing selected price must not be inferred",
            }),
        )
    resolutions = apply_reviewed_price_resolutions(
        prices,
        _review({
            "manufacturer": "AMD",
            "exact_model": "Ryzen 5 5600X",
            "listing_url": "https://hacom.vn/cpu-amd-ryzen-5-5600x",
            "variant": "RETAIL_BOXED",
            "selected_price_vnd": 4299000,
            "rationale": "Retail CPU price, not the observed bundle value.",
        }),
    )
    assert resolutions[0]["selected_price_vnd"] == 4299000
    assert resolutions[0]["selected_price_vnd"] != 3699000
    assert resolutions[0]["selected_price_found_in_crawler_observations"] is False


def test_unknown_listing_url_is_rejected() -> None:
    prices = [_price("Ryzen 5 5600X", "https://hacom.vn/cpu-amd-ryzen-5-5600x", "3.699.000")]
    with pytest.raises(ValueError, match="no matching raw crawler observation"):
        apply_reviewed_price_resolutions(
            prices,
            _review({
                "manufacturer": "AMD",
                "exact_model": "Ryzen 5 5600X",
                "listing_url": "https://hacom.vn/not-a-real-listing",
                "variant": "RETAIL_BOXED",
                "selected_price_vnd": 4299000,
                "rationale": "URL was not observed.",
            }),
        )


def test_duplicate_review_identities_are_rejected() -> None:
    record = {
        "manufacturer": "AMD",
        "exact_model": "Ryzen 5 5600X",
        "listing_url": "https://hacom.vn/cpu-amd-ryzen-5-5600x",
        "variant": "RETAIL_BOXED",
        "selected_price_vnd": 4299000,
        "rationale": "duplicate",
    }
    with pytest.raises(ValueError, match="identities must be unique"):
        ReviewedPriceFile.model_validate(_review(record, record))


def test_attach_price_resolutions_does_not_rewrite_raw_prices() -> None:
    candidates = {
        "technical": [],
        "prices": [_price("Ryzen 5 5600X", "https://hacom.vn/cpu-amd-ryzen-5-5600x", "3.699.000")],
    }
    original_prices = copy.deepcopy(candidates["prices"])
    resolutions = apply_reviewed_price_resolutions(
        candidates["prices"],
        _review({
            "manufacturer": "AMD",
            "exact_model": "Ryzen 5 5600X",
            "listing_url": "https://hacom.vn/cpu-amd-ryzen-5-5600x",
            "variant": "RETAIL_BOXED",
            "selected_price_vnd": 4299000,
            "rationale": "Retail CPU price.",
        }),
    )
    attached = attach_price_resolutions(candidates, resolutions)
    assert attached["prices"] == original_prices
    assert attached["prices"] is candidates["prices"]
    assert attached["price_resolutions"] == resolutions
    markdown = render_review_queue(run_label="test-run", prices=attached["prices"], resolutions=resolutions)
    assert "4.299.000" in markdown
    assert "3.699.000" in markdown
    assert "PRICE_REVIEWED_PENDING_TECHNICAL_AND_BENCHMARK" in markdown


def test_production_price_review_collapses_duplicates_and_keeps_tray_boxed_pairs() -> None:
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    original_prices = copy.deepcopy(candidates["prices"])
    resolutions = apply_reviewed_price_resolutions(candidates["prices"], review)
    assert candidates["prices"] == original_prices
    assert len(original_prices) == 41
    assert len(resolutions) == 23
    assert len({item["listing_url"] for item in resolutions}) == 23
    assert len({(item["exact_model"], item["variant"]) for item in resolutions}) == 23

    by_model: dict[str, list[dict]] = {}
    for item in resolutions:
        by_model.setdefault(item["exact_model"], []).append(item)

    athlon = by_model["Athlon 3000G"]
    assert len(athlon) == 1
    assert athlon[0]["selected_price_vnd"] == 1299000
    assert athlon[0]["raw_observation_count"] == 2

    assert by_model["Ryzen 5 4600G"][0]["selected_price_vnd"] == 2799000
    assert by_model["Ryzen 5 4600G"][0]["selected_price_found_in_crawler_observations"] is False
    assert by_model["Ryzen 5 5500"][0]["selected_price_vnd"] == 2599000
    assert by_model["Ryzen 5 5500GT"][0]["selected_price_vnd"] == 3799000
    assert len(by_model["Ryzen 5 5500GT"]) == 1
    assert by_model["Ryzen 5 5500GT"][0]["listing_url"].endswith("socket-am4")
    assert all(
        item["listing_url"] != "https://hacom.vn/cpu-amd-ryzen-5-5500gt-cpua0322"
        for item in resolutions
    )

    tray_boxed = {
        "Ryzen 5 7500F": {("TRAY_NO_BOX", 4199000), ("RETAIL_BOXED", 5199000)},
        "Ryzen 7 7800X3D": {("TRAY_NO_BOX", 8999000), ("RETAIL_BOXED", 9999000)},
        "Ryzen 7 9850X3D": {("TRAY_NO_BOX", 13999000), ("RETAIL_BOXED", 14699000)},
        "Ryzen 9 9950X": {("TRAY_NO_BOX", 13799000), ("RETAIL_BOXED", 16999000)},
        "RYZEN 9 9950X3D": {("TRAY_NO_BOX", 18899000), ("RETAIL_BOXED", 20899000)},
    }
    for model, expected in tray_boxed.items():
        assert {(item["variant"], item["selected_price_vnd"]) for item in by_model[model]} == expected

    expected_singles = {
        "Ryzen 5 5600X": 4299000,
        "Ryzen 5 7500X3D": 6599999,
        "Ryzen 5 7600X": 6199000,
        "Ryzen 7 7700X": 9599000,
        "Ryzen 7 9700X": 9999000,
        "Ryzen 7 9800X3D": 13499000,
        "Ryzen 9 7900X": 10899000,
        "Ryzen 9 9900X": 11999000,
        "RYZEN 9 9900X3D": 17499000,
    }
    for model, price in expected_singles.items():
        assert len(by_model[model]) == 1
        assert by_model[model][0]["selected_price_vnd"] == price
        assert by_model[model][0]["variant"] == "RETAIL_BOXED"
