import type { Metadata } from "next";
import { BuilderSection } from "../builder-section";
import styles from "../page.module.css";

export const metadata: Metadata = {
  title: "Start your build",
};

export default function BuildPage() {
  return (
    <main className={styles.shell}>
      <section className={styles.intro} aria-labelledby="builder-heading">
        <h1 id="builder-heading">Start your build</h1>
        <p>
          Choose one part per category. The backend checks compatibility and PSU headroom against the persisted catalog.
        </p>
      </section>
      <BuilderSection />
    </main>
  );
}