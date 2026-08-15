-- AI-Assisted PC Configuration System — PostgreSQL schema v0.1
-- Scope: curated catalog, evidence, prices, benchmarks, CPU↔motherboard
-- support exceptions, builds, and persisted deterministic analyses.
-- JSONB content is validated at the application boundary by typed Pydantic models.
-- This DDL is intentionally unchanged by the v0.1 contract/seed update.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE component_type AS ENUM
  ('CPU', 'MOTHERBOARD', 'RAM', 'GPU', 'STORAGE', 'PSU', 'CASE', 'COOLER');
CREATE TYPE source_type AS ENUM
  ('MANUFACTURER', 'OFFICIAL_DOCUMENTATION', 'TRUSTED_SECONDARY', 'RETAILER', 'MANUAL_CURATED');
CREATE TYPE availability_status AS ENUM ('IN_STOCK', 'OUT_OF_STOCK', 'PREORDER', 'UNKNOWN');
CREATE TYPE cpu_motherboard_support_status AS ENUM ('SUPPORTED', 'UNSUPPORTED', 'UNKNOWN');
CREATE TYPE build_analysis_status AS ENUM
  ('COMPATIBLE', 'COMPATIBLE_WITH_WARNINGS', 'INCOMPATIBLE');

CREATE TABLE data_sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(200) NOT NULL,
  source_type source_type NOT NULL,
  publisher VARCHAR(200),
  url TEXT NOT NULL UNIQUE,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE components (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  component_type component_type NOT NULL,
  manufacturer VARCHAR(100) NOT NULL,
  model VARCHAR(200) NOT NULL,
  specifications JSONB NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_components_identity UNIQUE (manufacturer, model, component_type),
  CONSTRAINT uq_components_id_type UNIQUE (id, component_type),
  CONSTRAINT ck_components_specifications_object CHECK (jsonb_typeof(specifications) = 'object')
);

CREATE TABLE component_sources (
  component_id UUID NOT NULL REFERENCES components(id) ON DELETE RESTRICT,
  source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE RESTRICT,
  verified_at TIMESTAMPTZ NOT NULL,
  notes TEXT,
  PRIMARY KEY (component_id, source_id)
);

CREATE TABLE component_prices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  component_id UUID NOT NULL REFERENCES components(id) ON DELETE RESTRICT,
  source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE RESTRICT,
  retailer_name VARCHAR(200) NOT NULL,
  listing_url TEXT NOT NULL,
  price_vnd NUMERIC(14,0) NOT NULL,
  availability availability_status,
  verified_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT ck_component_prices_nonnegative CHECK (price_vnd >= 0)
);

CREATE TABLE benchmark_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  component_id UUID NOT NULL REFERENCES components(id) ON DELETE RESTRICT,
  source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE RESTRICT,
  benchmark_name VARCHAR(200) NOT NULL,
  metric_name VARCHAR(200) NOT NULL,
  metric_value NUMERIC(18,4) NOT NULL,
  metric_unit VARCHAR(50) NOT NULL,
  test_context JSONB NOT NULL DEFAULT '{}'::jsonb,
  verified_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT ck_benchmark_context_object CHECK (jsonb_typeof(test_context) = 'object')
);

CREATE TABLE cpu_motherboard_support (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cpu_id UUID NOT NULL REFERENCES components(id) ON DELETE RESTRICT,
  motherboard_id UUID NOT NULL REFERENCES components(id) ON DELETE RESTRICT,
  status cpu_motherboard_support_status NOT NULL,
  min_bios_version VARCHAR(100),
  source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE RESTRICT,
  verified_at TIMESTAMPTZ NOT NULL,
  notes TEXT,
  CONSTRAINT uq_cpu_motherboard_support UNIQUE (cpu_id, motherboard_id),
  CONSTRAINT ck_cpu_motherboard_support_distinct CHECK (cpu_id <> motherboard_id)
);

CREATE TABLE builds (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(200) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE build_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  build_id UUID NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
  component_id UUID NOT NULL,
  component_type component_type NOT NULL,
  quantity SMALLINT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_build_items_component_type
    FOREIGN KEY (component_id, component_type)
    REFERENCES components(id, component_type) ON DELETE RESTRICT,
  CONSTRAINT uq_build_items_component UNIQUE (build_id, component_id),
  CONSTRAINT ck_build_items_quantity_positive CHECK (quantity > 0)
);

CREATE TABLE analysis_results (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  build_id UUID NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
  engine_version VARCHAR(100) NOT NULL,
  status build_analysis_status NOT NULL,
  summary JSONB NOT NULL,
  findings JSONB NOT NULL,
  assumptions JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_analysis_summary_object CHECK (jsonb_typeof(summary) = 'object'),
  CONSTRAINT ck_analysis_findings_array CHECK (jsonb_typeof(findings) = 'array'),
  CONSTRAINT ck_analysis_assumptions_array CHECK (jsonb_typeof(assumptions) = 'array')
);

CREATE INDEX ix_components_type_active ON components (component_type, active);
CREATE INDEX ix_components_specifications_gin ON components USING GIN (specifications jsonb_path_ops);
CREATE INDEX ix_component_sources_source ON component_sources (source_id);
CREATE INDEX ix_component_prices_component_verified ON component_prices (component_id, verified_at DESC);
CREATE INDEX ix_component_prices_source ON component_prices (source_id);
CREATE INDEX ix_benchmark_records_component_name ON benchmark_records (component_id, benchmark_name);
CREATE INDEX ix_cpu_mb_support_motherboard ON cpu_motherboard_support (motherboard_id);
CREATE INDEX ix_build_items_build ON build_items (build_id);
CREATE INDEX ix_analysis_results_build_created ON analysis_results (build_id, created_at DESC);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_components_set_updated_at
BEFORE UPDATE ON components FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_builds_set_updated_at
BEFORE UPDATE ON builds FOR EACH ROW EXECUTE FUNCTION set_updated_at();
