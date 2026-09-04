"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./page.module.css";

const NAV = [
  { href: "/build", label: "Tự chọn linh kiện" },
  { href: "/recommend", label: "Gợi ý cấu hình" },
] as const;

export function SiteShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Link className={styles.logo} href="/">
          BuildWise
        </Link>
        <nav aria-label="Điều hướng chính">
          {NAV.map((item) => (
            <Link key={item.href} href={item.href} aria-current={pathname === item.href ? "page" : undefined}>
              {item.label}
            </Link>
          ))}
        </nav>
      </header>
      {children}
      <footer className={styles.footer}>
        Giá và tình trạng hàng là dữ liệu được ghi nhận theo thời điểm, không phải cam kết tồn kho hiện tại. Kết quả tương thích
        và điện năng do hệ thống xác định; điểm số là chỉ báo heuristic, không phải dự đoán FPS.
      </footer>
    </div>
  );
}
