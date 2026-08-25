"use client";

import { useEffect, useState } from "react";
import { ApiError, CatalogDataset, listCatalogDatasets } from "../lib/recommendation-api";
import { BuilderSection } from "./builder-section";
import { RecommendSection } from "./recommend-section";
import styles from "./page.module.css";

export default function Home() {
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
        const firstReady = payload.catalog_datasets.find((dataset) => dataset.status === "READY");
        setSelectedDataset(firstReady?.dataset_version ?? "");
        setCatalogState("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setCatalogState("error");
        setCatalogError(error instanceof ApiError ? error.message : "Catalog datasets could not be loaded.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <a className={styles.logo} href="#top">
          BuildWise
        </a>
        <nav aria-label="Primary">
          <a href="#start-build">Start your build</a>
          <a href="#recommend">Recommended build</a>
        </nav>
      </header>

      <main id="top" className={styles.shell}>
        <section className={styles.intro} aria-labelledby="intro-heading">
          <h1 id="intro-heading">Pick the parts. We’ll tell you if they belong in the same PC.</h1>
          <p>
            BuildWise is a Vietnam / VND catalog builder. Choose components yourself to check compatibility and power, or ask the engine for a budget-aware recommendation. The page never invents sockets, wattage, or scores.
          </p>
        </section>

        <div id="start-build">
          <BuilderSection
            datasets={datasets}
            selectedDataset={selectedDataset}
            onDatasetChange={setSelectedDataset}
            catalogState={catalogState}
            catalogError={catalogError}
          />
        </div>

        <div id="recommend">
          <RecommendSection
            datasets={datasets}
            selectedDataset={selectedDataset}
            onDatasetChange={setSelectedDataset}
            catalogState={catalogState}
          />
        </div>
      </main>

      <footer className={styles.footer}>
        Prices are dated listing snapshots, not a current stock guarantee. Compatibility and power results come from the deterministic backend. Scores are heuristic indicators, not FPS predictions.
      </footer>
    </div>
  );
}
