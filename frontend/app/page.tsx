import Link from "next/link";
import styles from "./page.module.css";

export default function Home() {
  return (
    <main className={styles.shell}>
      <section className={styles.intro} aria-labelledby="intro-heading">
        <h1 id="intro-heading">Chọn linh kiện. BuildWise sẽ kiểm tra chúng có thể dùng chung trong một bộ PC hay không.</h1>
        <p>
          BuildWise hỗ trợ người mua PC tại Việt Nam với giá VND. Bạn có thể tự chọn linh kiện để kiểm tra tương thích và điện năng,
          hoặc nhận gợi ý cấu hình theo ngân sách. Hệ thống không tự tạo thông số socket, công suất hay điểm số.
        </p>
      </section>

      <section className={styles.feature} aria-labelledby="start-build-heading">
        <h2 id="start-build-heading">Tự chọn cấu hình</h2>
        <p className={styles.lede}>
          Chọn một linh kiện cho mỗi nhóm. Hệ thống sẽ kiểm tra tương thích và mức dự phòng công suất của PSU.
        </p>
        <p className={styles.featureActions}>
          <Link className={styles.cta} href="/build">
            Bắt đầu chọn linh kiện
          </Link>
        </p>
      </section>

      <section className={styles.feature} aria-labelledby="recommend-heading">
        <h2 id="recommend-heading">Nhận gợi ý cấu hình</h2>
        <p className={styles.lede}>
          Nhập ngân sách VND và nhu cầu sử dụng. Hệ thống sẽ tìm cấu hình khả thi và hiển thị bằng chứng cho từng kết quả.
        </p>
        <p className={styles.featureActions}>
          <Link className={styles.ctaSecondary} href="/recommend">
            Tìm cấu hình phù hợp
          </Link>
        </p>
      </section>
    </main>
  );
}
