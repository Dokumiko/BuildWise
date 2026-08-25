import {
  AnalysisFinding,
  BuildIndicators,
  SelectedPriceEvidence,
  WorkloadProfile,
} from "../lib/recommendation-api";
import { formatEvidenceValue, formatScore, formatVnd } from "../lib/format";
import styles from "./page.module.css";

const workloadLabels: Record<WorkloadProfile, string> = {
  gaming: "Gaming",
  productivity: "Productivity / Development",
  mixed: "Mixed workload",
};

export function FindingList({ findings }: { findings: AnalysisFinding[] }) {
  if (findings.length === 0) return null;
  return (
    <div className={styles.subsection}>
      <h3>Compatibility and power findings</h3>
      <div className={styles.findingList}>
        {findings.map((finding) => (
          <details
            className={[styles.finding, finding.severity === "ERROR" ? styles.findingError : finding.severity === "WARNING" ? styles.findingWarning : styles.findingInfo].join(" ")}
            key={`${finding.domain}-${finding.rule_id}`}
          >
            <summary>
              <span>{finding.severity}</span> {finding.message}
            </summary>
            <p>
              {finding.domain} · {finding.rule_id} · {finding.status}
            </p>
            <dl>
              {Object.entries(finding.evidence).map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{formatEvidenceValue(value)}</dd>
                </div>
              ))}
            </dl>
          </details>
        ))}
      </div>
    </div>
  );
}

export function PriceEvidence({ prices }: { prices: SelectedPriceEvidence[] }) {
  if (prices.length === 0) return null;
  return (
    <details className={styles.details}>
      <summary>Selected price evidence ({prices.length} components)</summary>
      <div className={styles.priceList}>
        {prices.map((price) => (
          <div className={styles.priceRow} key={`${price.component_type}-${price.manufacturer}-${price.model}`}>
            <div>
              <strong>
                {price.component_type}: {price.manufacturer} {price.model}
              </strong>
              <small>
                {price.retailer_name} · verified {new Date(price.verified_at).toLocaleDateString("vi-VN")}
              </small>
              <a href={price.listing_url} target="_blank" rel="noreferrer">
                View dated retailer listing
              </a>
            </div>
            <strong>{formatVnd(price.price_vnd)}</strong>
            <small>{price.availability_disclaimer}</small>
          </div>
        ))}
      </div>
    </details>
  );
}

export function ScoreEvidence({ indicators }: { indicators: BuildIndicators | null }) {
  if (!indicators) return null;
  return (
    <details className={styles.details}>
      <summary>Score evidence and limitations</summary>
      <p className={styles.muted}>
        Workload: {workloadLabels[indicators.workload]}. Values below are returned by the backend; this UI does not recalculate them.
      </p>
      <div className={styles.scoreList}>
        {Object.entries(indicators.component_indicators).map(([name, indicator]) => (
          <div key={name}>
            <span>{name}</span>
            <strong>{formatScore(indicator.value)}</strong>
            <small>{indicator.method}</small>
          </div>
        ))}
      </div>
      {Object.entries(indicators.omitted_indicators).map(([name, reason]) => (
        <p className={styles.notice} key={name}>
          <strong>{name} omitted:</strong> {reason}
        </p>
      ))}
    </details>
  );
}
