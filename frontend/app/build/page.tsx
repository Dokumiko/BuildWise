import type { Metadata } from "next";
import { BuilderSection } from "../builder-section";
import styles from "../page.module.css";

export const metadata: Metadata = {
  title: "Tự chọn cấu hình",
};

export default function BuildPage() {
  return (
    <main className={styles.shell}>
      <section className={styles.intro} aria-labelledby="builder-heading">
        <h1 id="builder-heading">Tự chọn cấu hình</h1>
        <p>
          Chọn một linh kiện cho mỗi nhóm. Hệ thống kiểm tra tương thích và mức dự phòng công suất của PSU dựa trên catalog đã chọn.
        </p>
      </section>
      <BuilderSection />
    </main>
  );
}
