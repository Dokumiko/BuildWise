"""SQLAlchemy metadata for the frozen relational schema v0.1.

Component-specific JSONB fields stay in Pydantic contracts rather than columns.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum as SqlEnum, ForeignKey, ForeignKeyConstraint, Numeric, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ComponentType(str, Enum): CPU="CPU"; MOTHERBOARD="MOTHERBOARD"; RAM="RAM"; GPU="GPU"; STORAGE="STORAGE"; PSU="PSU"; CASE="CASE"; COOLER="COOLER"
class SourceType(str, Enum): MANUFACTURER="MANUFACTURER"; OFFICIAL_DOCUMENTATION="OFFICIAL_DOCUMENTATION"; TRUSTED_SECONDARY="TRUSTED_SECONDARY"; RETAILER="RETAILER"; MANUAL_CURATED="MANUAL_CURATED"
class AvailabilityStatus(str, Enum): IN_STOCK="IN_STOCK"; OUT_OF_STOCK="OUT_OF_STOCK"; PREORDER="PREORDER"; UNKNOWN="UNKNOWN"
class SupportStatus(str, Enum): SUPPORTED="SUPPORTED"; UNSUPPORTED="UNSUPPORTED"; UNKNOWN="UNKNOWN"
class AnalysisStatus(str, Enum): COMPATIBLE="COMPATIBLE"; COMPATIBLE_WITH_WARNINGS="COMPATIBLE_WITH_WARNINGS"; INCOMPATIBLE="INCOMPATIBLE"

class DataSource(Base):
    __tablename__="data_sources"; id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()); name: Mapped[str] = mapped_column(String(200)); source_type: Mapped[SourceType] = mapped_column(SqlEnum(SourceType, name="source_type")); publisher: Mapped[str | None] = mapped_column(String(200)); url: Mapped[str] = mapped_column(Text, unique=True); description: Mapped[str | None] = mapped_column(Text); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
class Component(Base):
    __tablename__="components"; __table_args__=(UniqueConstraint("manufacturer","model","component_type",name="uq_components_identity"),UniqueConstraint("id","component_type",name="uq_components_id_type"),CheckConstraint("jsonb_typeof(specifications) = 'object'",name="ck_components_specifications_object")); id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),primary_key=True,server_default=func.gen_random_uuid()); component_type: Mapped[ComponentType]=mapped_column(SqlEnum(ComponentType,name="component_type")); manufacturer: Mapped[str]=mapped_column(String(100)); model: Mapped[str]=mapped_column(String(200)); specifications: Mapped[dict]=mapped_column(JSONB); active: Mapped[bool]=mapped_column(Boolean,server_default="true"); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now()); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
class Build(Base):
    __tablename__="builds"; id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,server_default=func.gen_random_uuid()); name: Mapped[str]=mapped_column(String(200)); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now()); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
class BuildItem(Base):
    __tablename__="build_items"; __table_args__=(ForeignKeyConstraint(["component_id","component_type"],["components.id","components.component_type"],name="fk_build_items_component_type",ondelete="RESTRICT"),UniqueConstraint("build_id","component_id",name="uq_build_items_component"),CheckConstraint("quantity > 0",name="ck_build_items_quantity_positive")); id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,server_default=func.gen_random_uuid()); build_id: Mapped[uuid.UUID]=mapped_column(ForeignKey("builds.id",ondelete="CASCADE")); component_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True)); component_type: Mapped[ComponentType]=mapped_column(SqlEnum(ComponentType,name="component_type",create_type=False)); quantity: Mapped[int]=mapped_column(SmallInteger,server_default="1"); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
