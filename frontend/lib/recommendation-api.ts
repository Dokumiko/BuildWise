export type CatalogDatasetStatus = "READY" | "UNUSABLE";

export interface CatalogDataset {
  dataset_version: string;
  status: CatalogDatasetStatus;
  component_counts: Record<string, number> | null;
  issue_code: string | null;
  issue_message: string | null;
}

export interface CatalogDatasetListResponse {
  catalog_datasets: CatalogDataset[];
}

export type BudgetMode = "strict" | "approximate";
export type WorkloadProfile = "gaming" | "productivity" | "mixed";
export type CaseFormFactor = "MID_TOWER" | "MINI_TOWER" | "FULL_TOWER" | "SFF";

export interface RecommendationRequirements {
  budget_vnd: number;
  budget_mode: BudgetMode;
  primary_workload: WorkloadProfile;
  minimum_ram_capacity_gb?: number;
  minimum_storage_capacity_gb?: number;
  case_form_factor?: CaseFormFactor;
  market: "VN";
  currency: "VND";
}

export interface RecommendationRequest {
  dataset_version: string;
  requirements: RecommendationRequirements;
}

export interface ApiErrorDetail {
  code?: string;
  message?: string;
  dataset_version?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: ApiErrorDetail | null;

  constructor(status: number, detail: ApiErrorDetail | null) {
    super(detail?.message ?? "The deterministic recommendation service could not complete the request.");
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export interface SelectedPriceEvidence {
  component_type: string;
  manufacturer: string;
  model: string;
  retailer_name: string;
  listing_url: string;
  price_vnd: number;
  availability: string | null;
  verified_at: string;
  price_use_policy: string;
  availability_disclaimer: string;
}

export interface AnalysisFinding {
  domain: "COMPATIBILITY" | "POWER";
  rule_id: string;
  severity: "ERROR" | "WARNING" | "INFO";
  status: "PASS" | "FAIL" | "INSUFFICIENT_DATA";
  message: string;
  evidence: Record<string, unknown>;
}

export interface DeterministicAnalysis {
  engine_version: string;
  status: "COMPATIBLE" | "COMPATIBLE_WITH_WARNINGS" | "INCOMPATIBLE";
  summary: {
    compatibility_status: string;
    power_status: string;
    estimated_system_draw_w: string | null;
    minimum_required_psu_capacity_w: string | null;
    recommended_psu_capacity_w: string | null;
    selected_psu_capacity_w: string | null;
    headroom_w: string | null;
    power_policy_version: string;
  };
  findings: AnalysisFinding[];
  assumptions: string[];
}

export interface IndicatorEvidence {
  value: string | number;
  method: string;
  evidence: Record<string, unknown>;
}

export interface BuildIndicators {
  workload: WorkloadProfile;
  component_indicators: Record<string, IndicatorEvidence>;
  omitted_indicators: Record<string, string>;
  workload_performance_score: string | number | null;
  raw_value: string | number | null;
  normalized_value: string | number | null;
  power_quality_score: string | number | null;
  overall_score: string | number | null;
  overall_weights: Record<string, string | number>;
}

export interface ScoredBuild {
  component_identity: Array<{ component_type: string; manufacturer: string; model: string }>;
  total_price_vnd: number | null;
  selected_price_evidence: SelectedPriceEvidence[];
  analysis_status: string;
  feasible: boolean;
  analysis: DeterministicAnalysis;
  indicators: BuildIndicators | null;
}

export interface SearchResult {
  search_config_version: string;
  scoring_config_version: string;
  requirements: RecommendationRequirements;
  ranked_builds: ScoredBuild[];
  cheapest_feasible_baseline: ScoredBuild | null;
  component_local_baseline: {
    status: string;
    selected_build: ScoredBuild | null;
    reason: string;
  };
  metrics: {
    complete_builds_evaluated: number;
    feasible_builds_scored: number;
  };
}

export interface RecommendationResponse {
  dataset_version: string;
  result: SearchResult;
}

export interface CatalogPickerComponent {
  id: string;
  component_type: string;
  manufacturer: string;
  model: string;
  price_vnd: number;
  availability: string | null;
  listing_url: string;
  verified_at: string;
  availability_disclaimer: string;
}

export interface CatalogPickerListResponse {
  dataset_version: string;
  components: CatalogPickerComponent[];
}

export interface SourceEvidence {
  source_name: string;
  source_url: string;
  verified_at: string;
}

export interface SelectedCatalogComponent {
  id: string;
  component_type: string;
  manufacturer: string;
  model: string;
  sources: SourceEvidence[];
}

export interface ManualAnalysisResponse {
  build_id: string;
  analysis_result_id: string;
  engine_version: string;
  status: string;
  summary: DeterministicAnalysis["summary"];
  findings: AnalysisFinding[];
  assumptions: string[];
  selected_components: SelectedCatalogComponent[];
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        Accept: "application/json",
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(0, {
      message: "The deterministic backend is unavailable. Start the backend and try again.",
    });
  }

  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    const detail = isApiErrorPayload(payload) ? payload.detail : null;
    throw new ApiError(response.status, detail);
  }

  return response.json() as Promise<T>;
}

function isApiErrorPayload(value: unknown): value is { detail: ApiErrorDetail } {
  return (
    typeof value === "object" &&
    value !== null &&
    "detail" in value &&
    typeof value.detail === "object" &&
    value.detail !== null
  );
}

export function listCatalogDatasets(): Promise<CatalogDatasetListResponse> {
  return requestJson<CatalogDatasetListResponse>("/api/v1/catalog-datasets");
}

export function requestRecommendation(
  request: RecommendationRequest,
): Promise<RecommendationResponse> {
  return requestJson<RecommendationResponse>("/api/v1/recommendations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function listCatalogPickerComponents(
  datasetVersion: string,
): Promise<CatalogPickerListResponse> {
  return requestJson<CatalogPickerListResponse>(
    `/api/v1/catalog-datasets/${encodeURIComponent(datasetVersion)}/components`,
  );
}

export function analyzeManualBuild(
  request: { name: string; component_ids: string[] },
  signal?: AbortSignal,
): Promise<ManualAnalysisResponse> {
  return requestJson<ManualAnalysisResponse>("/api/v1/builds/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
}
