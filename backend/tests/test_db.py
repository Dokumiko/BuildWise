"""DB tests 1–10: validate DDL-level enums, keys, FKs, checks,
cascade/restrict behavior, and JSON root-shape constraints against
the real PostgreSQL schema.

These complement V01–V16 (Pydantic contract tests) and do not
assert individual JSONB field names.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


# ── DB-1: component_type enum accepts all canonical values ──────────
def test_db01_component_type_enum_accepts_canonical(db_session) -> None:
    for ct in ("CPU", "MOTHERBOARD", "RAM", "GPU", "STORAGE", "PSU", "CASE", "COOLER"):
        result = db_session.execute(
            text(f"SELECT '{ct}'::component_type")
        )
        assert result.scalar() == ct


# ── DB-2: component_type enum rejects invalid values ────────────────
def test_db02_component_type_enum_rejects_invalid(db_session) -> None:
    with pytest.raises(Exception):
        db_session.execute(text("SELECT 'MONITOR'::component_type"))


# ── DB-3: unique constraint on (manufacturer, model, component_type) ─
def test_db03_unique_component_identity(db_session) -> None:
    from tests.conftest import clear_catalog_tables

    clear_catalog_tables(db_session)

    db_session.execute(
        text(
            "INSERT INTO components (component_type, manufacturer, model, specifications) "
            "VALUES ('CPU', 'AMD', 'TestCPU', '{}'::jsonb)"
        )
    )
    db_session.flush()
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO components (component_type, manufacturer, model, specifications) "
                "VALUES ('CPU', 'AMD', 'TestCPU', '{}'::jsonb)"
            )
        )
        db_session.flush()


# ── DB-4: specifications JSONB must be an object ────────────────────
def test_db04_specifications_must_be_object(db_session) -> None:
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO components (component_type, manufacturer, model, specifications) "
                "VALUES ('CPU', 'AMD', 'BadSpec', '[]'::jsonb)"
            )
        )
        db_session.flush()


# ── DB-5: build_items quantity must be positive ─────────────────────
def test_db05_build_items_quantity_positive(db_session) -> None:
    from tests.conftest import clear_catalog_tables

    clear_catalog_tables(db_session)

    db_session.execute(
        text(
            "INSERT INTO components (id, component_type, manufacturer, model, specifications) "
            "VALUES (:cid, 'CPU', 'AMD', 'QtyTest', '{}'::jsonb)"
        ),
        {"cid": str(uuid.uuid4())},
    )
    build_id = str(uuid.uuid4())
    db_session.execute(
        text("INSERT INTO builds (id, name) VALUES (:bid, 'test')"),
        {"bid": build_id},
    )
    db_session.flush()

    comp_id = db_session.execute(
        text("SELECT id FROM components WHERE model = 'QtyTest'")
    ).scalar()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO build_items (build_id, component_id, component_type, quantity) "
                "VALUES (:bid, :cid, 'CPU', 0)"
            ),
            {"bid": build_id, "cid": str(comp_id)},
        )
        db_session.flush()


# ── DB-6: build_items FK enforces composite (id, component_type) ────
def test_db06_build_items_composite_fk(db_session) -> None:
    from tests.conftest import clear_catalog_tables

    clear_catalog_tables(db_session)

    comp_id = str(uuid.uuid4())
    db_session.execute(
        text(
            "INSERT INTO components (id, component_type, manufacturer, model, specifications) "
            "VALUES (:cid, 'CPU', 'AMD', 'FKTest', '{}'::jsonb)"
        ),
        {"cid": comp_id},
    )
    build_id = str(uuid.uuid4())
    db_session.execute(
        text("INSERT INTO builds (id, name) VALUES (:bid, 'test')"),
        {"bid": build_id},
    )
    db_session.flush()

    # Wrong component_type should fail the composite FK.
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO build_items (build_id, component_id, component_type, quantity) "
                "VALUES (:bid, :cid, 'GPU', 1)"
            ),
            {"bid": build_id, "cid": comp_id},
        )
        db_session.flush()


# ── DB-7: cascade DELETE on builds removes build_items ──────────────
def test_db07_build_cascade_deletes_items(db_session) -> None:
    from tests.conftest import clear_catalog_tables

    clear_catalog_tables(db_session)

    comp_id = str(uuid.uuid4())
    build_id = str(uuid.uuid4())
    db_session.execute(
        text(
            "INSERT INTO components (id, component_type, manufacturer, model, specifications) "
            "VALUES (:cid, 'RAM', 'G.Skill', 'CascTest', '{}'::jsonb)"
        ),
        {"cid": comp_id},
    )
    db_session.execute(
        text("INSERT INTO builds (id, name) VALUES (:bid, 'cascade')"),
        {"bid": build_id},
    )
    db_session.execute(
        text(
            "INSERT INTO build_items (build_id, component_id, component_type, quantity) "
            "VALUES (:bid, :cid, 'RAM', 2)"
        ),
        {"bid": build_id, "cid": comp_id},
    )
    db_session.flush()

    db_session.execute(
        text("DELETE FROM builds WHERE id = :bid"), {"bid": build_id}
    )
    db_session.flush()

    count = db_session.execute(
        text("SELECT count(*) FROM build_items WHERE build_id = :bid"),
        {"bid": build_id},
    ).scalar()
    assert count == 0


# ── DB-8: RESTRICT prevents deleting a component with links ────────
def test_db08_restrict_prevents_component_delete_with_source_link(db_session) -> None:
    from tests.conftest import clear_catalog_tables

    clear_catalog_tables(db_session)

    source_id = str(uuid.uuid4())
    comp_id = str(uuid.uuid4())
    db_session.execute(
        text(
            "INSERT INTO data_sources (id, name, source_type, url) "
            "VALUES (:sid, 'test', 'MANUFACTURER', 'https://example.com/restrict-test')"
        ),
        {"sid": source_id},
    )
    db_session.execute(
        text(
            "INSERT INTO components (id, component_type, manufacturer, model, specifications) "
            "VALUES (:cid, 'GPU', 'NVIDIA', 'RestrictTest', '{}'::jsonb)"
        ),
        {"cid": comp_id},
    )
    db_session.execute(
        text(
            "INSERT INTO component_sources (component_id, source_id, verified_at) "
            "VALUES (:cid, :sid, now())"
        ),
        {"cid": comp_id, "sid": source_id},
    )
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text("DELETE FROM components WHERE id = :cid"), {"cid": comp_id}
        )
        db_session.flush()


# ── DB-9: cpu_motherboard_support requires cpu_id != motherboard_id ─
def test_db09_cpu_motherboard_support_distinct_check(db_session) -> None:
    from tests.conftest import clear_catalog_tables

    clear_catalog_tables(db_session)

    comp_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    db_session.execute(
        text(
            "INSERT INTO components (id, component_type, manufacturer, model, specifications) "
            "VALUES (:cid, 'CPU', 'AMD', 'SelfRef', '{}'::jsonb)"
        ),
        {"cid": comp_id},
    )
    db_session.execute(
        text(
            "INSERT INTO data_sources (id, name, source_type, url) "
            "VALUES (:sid, 'test', 'MANUFACTURER', 'https://example.com/self-ref')"
        ),
        {"sid": source_id},
    )
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO cpu_motherboard_support "
                "(cpu_id, motherboard_id, status, source_id, verified_at) "
                "VALUES (:cid, :cid, 'SUPPORTED', :sid, now())"
            ),
            {"cid": comp_id, "sid": source_id},
        )
        db_session.flush()


# ── DB-10: analysis_results JSONB shape checks ─────────────────────
def test_db10_analysis_results_jsonb_shape_checks(db_session) -> None:
    from tests.conftest import clear_catalog_tables

    clear_catalog_tables(db_session)

    build_id = str(uuid.uuid4())
    db_session.execute(
        text("INSERT INTO builds (id, name) VALUES (:bid, 'analysis')"),
        {"bid": build_id},
    )
    db_session.flush()

    # summary must be object
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO analysis_results "
                "(build_id, engine_version, status, summary, findings) "
                "VALUES (:bid, '0.1', 'COMPATIBLE', '[]'::jsonb, '[]'::jsonb)"
            ),
            {"bid": build_id},
        )
        db_session.flush()


def test_db10b_analysis_findings_must_be_array(db_session) -> None:
    from tests.conftest import clear_catalog_tables

    clear_catalog_tables(db_session)

    build_id = str(uuid.uuid4())
    db_session.execute(
        text("INSERT INTO builds (id, name) VALUES (:bid, 'analysis')"),
        {"bid": build_id},
    )
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO analysis_results "
                "(build_id, engine_version, status, summary, findings) "
                "VALUES (:bid, '0.1', 'COMPATIBLE', '{}'::jsonb, '{}'::jsonb)"
            ),
            {"bid": build_id},
        )
        db_session.flush()


def test_db10c_analysis_assumptions_must_be_array(db_session) -> None:
    from tests.conftest import clear_catalog_tables

    clear_catalog_tables(db_session)

    build_id = str(uuid.uuid4())
    db_session.execute(
        text("INSERT INTO builds (id, name) VALUES (:bid, 'analysis')"),
        {"bid": build_id},
    )
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO analysis_results "
                "(build_id, engine_version, status, summary, findings, assumptions) "
                "VALUES (:bid, '0.1', 'COMPATIBLE', '{}'::jsonb, '[]'::jsonb, '{}'::jsonb)"
            ),
            {"bid": build_id},
        )
        db_session.flush()
