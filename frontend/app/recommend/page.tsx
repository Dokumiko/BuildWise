import type { Metadata } from "next";
import { RecommendSection } from "../recommend-section";
import styles from "../page.module.css";

export const metadata: Metadata = {
  title: "Gợi ý cấu hình",
};

export default function RecommendPage() {
  return (
    <main className={styles.shell}>
      <section className={styles.intro} aria-labelledby="recommend-heading">
        <h1 id="recommend-heading">Nhận gợi ý cấu hình</h1>
        <p>
          Nhập ngân sách VND và nhu cầu sử dụng. Hệ thống sẽ tìm các cấu hình khả thi, kèm giá, thông tin tương thích,
          điện năng và điểm số.
        </p>
      </section>
      <RecommendSection />
    </main>
  );
}
