from pathlib import Path

from app.scripts import import_evaluation_intake as command
from app.services.catalog_evaluation_import import CatalogEvaluationImportResult
from app.services.catalog_intake_persistence import IntakePersistenceResult


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class FakeSessionFactory:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __call__(self) -> FakeSession:
        return self.session


def _result() -> CatalogEvaluationImportResult:
    return CatalogEvaluationImportResult(
        dataset_version="test-dataset",
        persistence=IntakePersistenceResult(
            source_count=1,
            component_count=8,
            component_source_count=8,
            price_count=0,
            benchmark_count=0,
            excluded_component_count=0,
            skipped_price_count=0,
            skipped_benchmark_count=0,
            skipped_records=(),
        ),
    )


def test_import_script_commits_only_after_import_succeeds(monkeypatch, capsys) -> None:
    session = FakeSession()
    monkeypatch.setattr(command, "SessionLocal", FakeSessionFactory(session))
    monkeypatch.setattr(command, "import_catalog_evaluation_intake", lambda *args, **kwargs: _result())

    exit_code = command.main(["--path", str(Path("intake.json"))])

    assert exit_code == 0
    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True
    assert '"dataset_version": "test-dataset"' in capsys.readouterr().out


def test_import_script_rolls_back_and_hides_no_success_output_on_failure(monkeypatch, capsys) -> None:
    session = FakeSession()
    monkeypatch.setattr(command, "SessionLocal", FakeSessionFactory(session))

    def fail(*args, **kwargs):
        raise ValueError("invalid typed intake")

    monkeypatch.setattr(command, "import_catalog_evaluation_intake", fail)

    exit_code = command.main(["--path", "intake.json"])

    assert exit_code == 1
    assert session.committed is False
    assert session.rolled_back is True
    assert session.closed is True
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Catalog evaluation intake import failed: invalid typed intake" in captured.err
