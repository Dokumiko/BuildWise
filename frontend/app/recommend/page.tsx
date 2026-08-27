import type { Metadata } from "next";
import { RecommendSection } from "../recommend-section";
import styles from "../page.module.css";

export const metadata: Metadata = {
  title: "Recommended build",
};

export default function RecommendPage() {
  return (
    <main className={styles.shell}>
      <section className={styles.intro} aria-labelledby="recommend-heading">
        <h1 id="recommend-heading">Get a recommended build</h1>
        <p>
          Submit a VND budget and workload. The deterministic search returns feasible catalog builds with price,
          compatibility, power, and score evidence.
        </p>
      </section>
      <RecommendSection />
    </main>
  );
}