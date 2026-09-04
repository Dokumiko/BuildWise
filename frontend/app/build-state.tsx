"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  isManualBuildCategory,
  type ManualBuildCategory,
} from "../lib/manual-build";
import type { CatalogPickerComponent } from "../lib/recommendation-api";

const STORAGE_KEY = "buildwise-manual-build-v1";

type BuildSelection = Partial<Record<ManualBuildCategory, CatalogPickerComponent>>;
type StoredBuild = { datasetVersion: string; selected: BuildSelection };

type BuildStateValue = {
  datasetVersion: string;
  selected: BuildSelection;
  hydrated: boolean;
  setDatasetVersion: (value: string) => void;
  selectPart: (part: CatalogPickerComponent) => void;
  removePart: (componentType: ManualBuildCategory) => void;
};

const BuildStateContext = createContext<BuildStateValue | null>(null);

function isStoredPart(value: unknown, type: ManualBuildCategory): value is CatalogPickerComponent {
  return (
    typeof value === "object"
    && value !== null
    && "id" in value
    && "component_type" in value
    && "manufacturer" in value
    && "model" in value
    && "price_vnd" in value
    && typeof value.id === "string"
    && value.component_type === type
    && typeof value.manufacturer === "string"
    && typeof value.model === "string"
    && (typeof value.price_vnd === "number" || value.price_vnd === null)
  );
}

function readStoredBuild(): StoredBuild {
  if (typeof window === "undefined") return { datasetVersion: "", selected: {} };
  try {
    const parsed: unknown = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) ?? "null");
    if (!parsed || typeof parsed !== "object") return { datasetVersion: "", selected: {} };
    const value = parsed as Partial<StoredBuild>;
    const selected: BuildSelection = {};
    if (value.selected && typeof value.selected === "object") {
      for (const [type, part] of Object.entries(value.selected)) {
        if (isManualBuildCategory(type) && isStoredPart(part, type)) selected[type] = part;
      }
    }
    return {
      datasetVersion: typeof value.datasetVersion === "string" ? value.datasetVersion : "",
      selected,
    };
  } catch {
    return { datasetVersion: "", selected: {} };
  }
}

export function BuildStateProvider({ children }: { children: React.ReactNode }) {
  const [datasetVersion, setDatasetVersionState] = useState("");
  const [selected, setSelected] = useState<BuildSelection>({});
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const stored = readStoredBuild();
    setDatasetVersionState(stored.datasetVersion);
    setSelected(stored.selected);
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    try {
      const value: StoredBuild = { datasetVersion, selected };
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    } catch {
      // The in-memory selection continues to work if session storage is unavailable.
    }
  }, [datasetVersion, hydrated, selected]);

  const value = useMemo<BuildStateValue>(() => ({
    datasetVersion,
    selected,
    hydrated,
    setDatasetVersion(value) {
      setDatasetVersionState(value);
      setSelected({});
    },
    selectPart(part) {
      if (!isManualBuildCategory(part.component_type)) return;
      setSelected((current) => ({ ...current, [part.component_type]: part }));
    },
    removePart(componentType) {
      setSelected((current) => {
        const next = { ...current };
        delete next[componentType];
        return next;
      });
    },
  }), [datasetVersion, hydrated, selected]);

  return <BuildStateContext.Provider value={value}>{children}</BuildStateContext.Provider>;
}

export function useBuildState() {
  const value = useContext(BuildStateContext);
  if (!value) throw new Error("useBuildState must be used inside BuildStateProvider");
  return value;
}
