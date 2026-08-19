"""SQLAlchemy metadata for the frozen relational schema v0.1.

Must match backend/data/database-schema-v0.1.sql exactly.
Component-specific JSONB fields stay in Pydantic contracts rather than columns.
Triggers (set_updated_at) remain in SQL; ORM only declares columns/indexes/constraints.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ComponentType(str, Enum):
    CPU = "CPU"
    MOTHERBOARD = "MOTHERBOARD"
    RAM = "RAM"
    GPU = "GPU"
    STORAGE = "STORAGE"
    PSU = "PSU"
    CASE = "CASE"
    COOLER = "COOLER"


class SourceType(str, Enum):
    MANUFACTURER = "MANUFACTURER"
    OFFICIAL_DOCUMENTATION = "OFFICIAL_DOCUMENTATION"
    TRUSTED_SECONDARY = "TRUSTED_SECONDARY"
    RETAILER = "RETAILER"
    MANUAL_CURATED = "MANUAL_CURATED"


class AvailabilityStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    PREORDER = "PREORDER"
    UNKNOWN = "UNKNOWN"


class SupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class AnalysisStatus(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    COMPATIBLE_WITH_WARNINGS = "COMPATIBLE_WITH_WARNINGS"
    INCOMPATIBLE = "INCOMPATIBLE"


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        SqlEnum(SourceType, name="source_type"), nullable=False
    )
    publisher: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Component(Base):
    __tablename__ = "components"
    __table_args__ = (
        UniqueConstraint(
            "manufacturer", "model", "component_type", name="uq_components_identity"
        ),
        UniqueConstraint("id", "component_type", name="uq_components_id_type"),
        CheckConstraint(
            "jsonb_typeof(specifications) = 'object'",
            name="ck_components_specifications_object",
        ),
        Index("ix_components_type_active", "component_type", "active"),
        Index(
            "ix_components_specifications_gin",
            "specifications",
            postgresql_using="gin",
            postgresql_ops={"specifications": "jsonb_path_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    component_type: Mapped[ComponentType] = mapped_column(
        SqlEnum(ComponentType, name="component_type"), nullable=False
    )
    manufacturer: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    specifications: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ComponentSource(Base):
    __tablename__ = "component_sources"
    __table_args__ = (
        PrimaryKeyConstraint("component_id", "source_id"),
        Index("ix_component_sources_source", "source_id"),
    )

    component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("components.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("data_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)


class ComponentPrice(Base):
    __tablename__ = "component_prices"
    __table_args__ = (
        CheckConstraint("price_vnd >= 0", name="ck_component_prices_nonnegative"),
        Index(
            "ix_component_prices_component_verified",
            "component_id",
            text("verified_at DESC"),
        ),
        Index("ix_component_prices_source", "source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("components.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("data_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    retailer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    listing_url: Mapped[str] = mapped_column(Text, nullable=False)
    price_vnd: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    availability: Mapped[AvailabilityStatus | None] = mapped_column(
        SqlEnum(AvailabilityStatus, name="availability_status")
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class BenchmarkRecord(Base):
    __tablename__ = "benchmark_records"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(test_context) = 'object'",
            name="ck_benchmark_context_object",
        ),
        Index(
            "ix_benchmark_records_component_name",
            "component_id",
            "benchmark_name",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("components.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("data_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    benchmark_name: Mapped[str] = mapped_column(String(200), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False)
    metric_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    metric_unit: Mapped[str] = mapped_column(String(50), nullable=False)
    test_context: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class CpuMotherboardSupport(Base):
    __tablename__ = "cpu_motherboard_support"
    __table_args__ = (
        UniqueConstraint("cpu_id", "motherboard_id", name="uq_cpu_motherboard_support"),
        CheckConstraint(
            "cpu_id <> motherboard_id",
            name="ck_cpu_motherboard_support_distinct",
        ),
        Index("ix_cpu_mb_support_motherboard", "motherboard_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    cpu_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("components.id", ondelete="RESTRICT"),
        nullable=False,
    )
    motherboard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("components.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[SupportStatus] = mapped_column(
        SqlEnum(SupportStatus, name="cpu_motherboard_support_status"),
        nullable=False,
    )
    min_bios_version: Mapped[str | None] = mapped_column(String(100))
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("data_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)


class Build(Base):
    __tablename__ = "builds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BuildItem(Base):
    __tablename__ = "build_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["component_id", "component_type"],
            ["components.id", "components.component_type"],
            name="fk_build_items_component_type",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("build_id", "component_id", name="uq_build_items_component"),
        CheckConstraint("quantity > 0", name="ck_build_items_quantity_positive"),
        Index("ix_build_items_build", "build_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    build_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("builds.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    component_type: Mapped[ComponentType] = mapped_column(
        SqlEnum(ComponentType, name="component_type", create_type=False),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(summary) = 'object'",
            name="ck_analysis_summary_object",
        ),
        CheckConstraint(
            "jsonb_typeof(findings) = 'array'",
            name="ck_analysis_findings_array",
        ),
        CheckConstraint(
            "jsonb_typeof(assumptions) = 'array'",
            name="ck_analysis_assumptions_array",
        ),
        Index(
            "ix_analysis_results_build_created",
            "build_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    build_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("builds.id", ondelete="CASCADE"),
        nullable=False,
    )
    engine_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[AnalysisStatus] = mapped_column(
        SqlEnum(AnalysisStatus, name="build_analysis_status"),
        nullable=False,
    )
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    findings: Mapped[list] = mapped_column(JSONB, nullable=False)
    assumptions: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
