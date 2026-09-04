import type { Metadata } from "next";
import { Suspense } from "react";
import { ComponentSelection } from "../../component-selection";
import styles from "../../page.module.css";

export const metadata: Metadata = { title: "Choose a component" };

export default function ComponentSelectionPage() {
  return (
    <main className={styles.shell}>
      <Suspense fallback={<section className={styles.section}><p className={styles.muted}>Loading component selector...</p></section>}>
        <ComponentSelection />
      </Suspense>
    </main>
  );
}
