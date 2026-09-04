import type { Metadata } from "next";
import { Suspense } from "react";
import { ComponentSelection } from "../../component-selection";
import styles from "../../page.module.css";

export const metadata: Metadata = { title: "Chọn linh kiện" };

export default function ComponentSelectionPage() {
  return (
    <main className={styles.shell}>
      <Suspense fallback={<section className={styles.section}><p className={styles.muted}>Đang tải danh sách linh kiện...</p></section>}>
        <ComponentSelection />
      </Suspense>
    </main>
  );
}
