import hashlib
import json
from pathlib import Path

from app.scripts import run_search_evaluation as command


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeSessionFactory:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __call__(self) -> FakeSession:
        return self.session


class FakeEvaluation:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def model_dump(self, *, mode: str) -> dict:
        assert mode == "json"
        return self.payload


def _write_scenarios(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "scenario_id": "gaming-feasible",
                    "requirements": {
                        "budget_vnd": 35_000_000,
                        "budget_mode": "strict",
                        "primary_workload": "gaming",
                        "minimum_ram_capacity_gb": 32,
                        "minimum_storage_capacity_gb": 1000,
                    },
                }
            ]
        ),
        encoding="utf-8",
    )


def test_evaluation_script_runs_caller_scenarios_and_emits_versioned_report(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    scenarios_path = tmp_path / "scenarios.json"
    scoring_configs_path = tmp_path / "scoring-configs.json"
    _write_scenarios(scenarios_path)
    scoring_configs_path.write_text(
        json.dumps([{"version": "sensitivity-default"}]), encoding="utf-8"
    )
    session = FakeSession()
    captured: dict[str, object] = {}
    monkeypatch.setattr(command, "SessionLocal", FakeSessionFactory(session))

    def evaluate_search(session_arg, scenarios, **kwargs):
        captured["search_session"] = session_arg
        captured["search_scenarios"] = scenarios
        captured["search_kwargs"] = kwargs
        return FakeEvaluation({"kind": "search"})

    def evaluate_sensitivity(session_arg, scenarios, **kwargs):
        captured["sensitivity_session"] = session_arg
        captured["sensitivity_scenarios"] = scenarios
        captured["sensitivity_kwargs"] = kwargs
        return FakeEvaluation({"kind": "sensitivity"})

    monkeypatch.setattr(command, "evaluate_persisted_search_scenarios", evaluate_search)
    monkeypatch.setattr(command, "evaluate_persisted_scoring_sensitivity", evaluate_sensitivity)

    exit_code = command.main(
        [
            "--dataset-version",
            "vn-pc-am5-ddr5-v0.2",
            "--scenarios",
            str(scenarios_path),
            "--scenario-set-version",
            "operations-smoke-v0.1",
            "--scoring-configs",
            str(scoring_configs_path),
        ]
    )

    assert exit_code == 0
    assert session.closed is True
    assert captured["search_session"] is session
    assert captured["sensitivity_session"] is session
    assert [item.scenario_id for item in captured["search_scenarios"]] == ["gaming-feasible"]
    assert captured["search_kwargs"]["dataset_version"] == "vn-pc-am5-ddr5-v0.2"
    assert captured["search_kwargs"]["evaluation_config"].pruning_k_values == (3, 5, 10, 20)
    assert captured["sensitivity_kwargs"]["scoring_configs"][0].version == "sensitivity-default"
    assert json.loads(capsys.readouterr().out) == {
        "dataset_version": "vn-pc-am5-ddr5-v0.2",
        "report_schema_version": "search-evaluation-report-0.1",
        "scenario_set_version": "operations-smoke-v0.1",
        "scenario_file_sha256": hashlib.sha256(scenarios_path.read_bytes()).hexdigest(),
        "evaluation_config": {
            "version": "search-evaluation-0.1.0",
            "pruning_k_values": [3, 5, 10, 20],
            "reference_pruning_k": None,
            "reference_top_n": 3,
            "repetitions": 1,
        },
        "search_scoring_config": {
            "version": "scoring-0.1.0",
            "mixed_alpha": "0.5",
            "gaming_weights": {"gpu": "0.60", "cpu": "0.30", "ram": "0.05", "storage": "0.05"},
            "productivity_weights": {"gpu": "0.05", "cpu": "0.60", "ram": "0.20", "storage": "0.15"},
            "gaming_overall_weights": {"performance": "0.60", "value": "0.25", "power": "0.15"},
            "productivity_overall_weights": {"performance": "0.55", "value": "0.30", "power": "0.15"},
            "power_quality_cap_ratio": "1",
        },
        "scoring_configs": [
            {
                "version": "sensitivity-default",
                "mixed_alpha": "0.5",
                "gaming_weights": {
                    "gpu": "0.60",
                    "cpu": "0.30",
                    "ram": "0.05",
                    "storage": "0.05",
                },
                "productivity_weights": {
                    "gpu": "0.05",
                    "cpu": "0.60",
                    "ram": "0.20",
                    "storage": "0.15",
                },
                "gaming_overall_weights": {
                    "performance": "0.60",
                    "value": "0.25",
                    "power": "0.15",
                },
                "productivity_overall_weights": {
                    "performance": "0.55",
                    "value": "0.30",
                    "power": "0.15",
                },
                "power_quality_cap_ratio": "1",
            }
        ],
        "search_evaluation": {"kind": "search"},
        "scoring_sensitivity": {"kind": "sensitivity"},
    }


def test_evaluation_script_rejects_invalid_input_before_opening_database(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    scenarios_path = tmp_path / "scenarios.json"
    scenarios_path.write_text("[]", encoding="utf-8")

    def fail_if_opened():
        raise AssertionError("database session must not be opened for invalid input")

    monkeypatch.setattr(command, "SessionLocal", fail_if_opened)

    exit_code = command.main(
        [
            "--dataset-version",
            " vn-pc-am5-ddr5-v0.2",
            "--scenarios",
            str(scenarios_path),
            "--scenario-set-version",
            "operations-smoke-v0.1",
        ]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "dataset_version must be non-empty" in captured.err


def test_evaluation_script_closes_session_when_persisted_catalog_is_rejected(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    scenarios_path = tmp_path / "scenarios.json"
    _write_scenarios(scenarios_path)
    session = FakeSession()
    monkeypatch.setattr(command, "SessionLocal", FakeSessionFactory(session))

    def rejected(*args, **kwargs):
        raise ValueError("persisted catalog evidence is invalid")

    monkeypatch.setattr(command, "evaluate_persisted_search_scenarios", rejected)

    exit_code = command.main(
        [
            "--dataset-version",
            "vn-pc-am5-ddr5-v0.2",
            "--scenarios",
            str(scenarios_path),
            "--scenario-set-version",
            "operations-smoke-v0.1",
        ]
    )

    assert exit_code == 1
    assert session.closed is True
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Search evaluation failed: persisted catalog evidence is invalid" in captured.err
