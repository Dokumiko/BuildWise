"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./page.module.css";

const NAV = [
  { href: "/build", label: "Start your build" },
  { href: "/recommend", label: "Recommended build" },
] as const;

export function SiteShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Link className={styles.logo} href="/">
          BuildWise
        </Link>
        <nav aria-label="Primary">
          {NAV.map((item) => (
            <Link key={item.href} href={item.href} aria-current={pathname === item.href ? "page" : undefined}>
              {item.label}
            </Link>
          ))}
        </nav>
      </header>
      {children}
      <footer className={styles.footer}>
        Prices are dated listing snapshots, not a current stock guarantee. Compatibility and power results come from the
        deterministic backend. Scores are heuristic indicators, not FPS predictions.
      </footer>
    </div>
  );
}