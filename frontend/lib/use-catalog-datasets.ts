"use client";

import { useEffect, useState } from "react";
import { ApiError, CatalogDataset, listCatalogDatasets } from "./recommendation-api";
import { DEFAULT_DATASET_VERSION } from "./catalog";

export function useCatalogDatasets() {
  const [datasets, setDatasets] = useState<CatalogDataset[]>([]);
  const [selectedDataset, setSelectedDataset] = useState("");
  const [catalogState, setCatalogState] = useState<"loading" | "ready" | "error">("loading");
  const [catalogError, setCatalogError] = useState("");

  useEffect(() => {
    let cancelled = false;
    listCatalogDatasets()
      .then((payload) => {
        if (cancelled) return;
        setDatasets(payload.catalog_datasets);
        const defaultDataset = payload.catalog_datasets.find(
          (dataset) => dataset.dataset_version === DEFAULT_DATASET_VERSION && dataset.status === "READY",
        );
        const firstReady = payload.catalog_datasets.find((dataset) => dataset.status === "READY");
        setSelectedDataset(defaultDataset?.dataset_version ?? firstReady?.dataset_version ?? "");
        setCatalogState("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setCatalogState("error");
        setCatalogError(error instanceof ApiError ? error.message : "Không thể tải dữ liệu linh kiện.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { datasets, selectedDataset, setSelectedDataset, catalogState, catalogError };
}
