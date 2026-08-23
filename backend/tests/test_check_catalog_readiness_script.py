import json
from pathlib import Path

from app.scripts import check_catalog_readiness as command


V02_INTAKE = (
    Path(__file__).parents[1] / "data" / "vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json"
)
V01_INTAKE = Path(__file__).parents[1] / "data" / "catalog-evaluation-intake-v0.1.json"


def test_readiness_script_reports_ready_v02_intake_without_database_access(capsys) -> None:
    exit_code = command.main(["--path", str(V02_INTAKE)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report["intake_dataset_version"] == "vn-pc-am5-ddr5-v0.2"
    assert report["scoring_ready"] is True
    assert report["constrained_search_ready"] is True
    assert report["canonical_component_counts"] == {
        "CASE": 2,
        "COOLER": 2,
        "CPU": 2,
        "GPU": 2,
        "MOTHERBOARD": 2,
        "PSU": 2,
        "RAM": 2,
        "STORAGE": 2,
    }


def test_readiness_script_reports_valid_but_unready_v01_intake_with_distinct_exit_code(
    capsys,
) -> None:
    exit_code = command.main(["--path", str(V01_INTAKE)])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report["intake_dataset_version"] == "vn-pc-am5-ddr5-v0.1"
    assert report["scoring_ready"] is False
    assert report["constrained_search_ready"] is False
    assert any(
        finding["finding_id"] == "CONSTRAINED_SEARCH_POOL_INSUFFICIENT"
        for finding in report["findings"]
    )


def test_readiness_script_rejects_unreadable_input_without_report(capsys, tmp_path) -> None:
    missing_path = tmp_path / "missing-intake.json"

    exit_code = command.main(["--path", str(missing_path)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Catalog readiness check failed:" in captured.err
    assert missing_path.name in captured.err
