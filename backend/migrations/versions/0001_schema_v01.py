"""Frozen schema v0.1 baseline.

The executable baseline remains `database-schema-v0.1.sql` from the approved
design package. This marker lets Alembic track an already-created v0.1 schema
without generating a different DDL implementation.
"""
revision = "0001_schema_v01"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Apply the approved database-schema-v0.1.sql before stamping this revision.
    pass

def downgrade() -> None:
    pass
