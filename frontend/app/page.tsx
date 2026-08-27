import Link from "next/link";
import styles from "./page.module.css";

export default function Home() {
  return (
    <main className={styles.shell}>
      <section className={styles.intro} aria-labelledby="intro-heading">
        <h1 id="intro-heading">Pick the parts. We&apos;ll tell you if they belong in the same PC.</h1>
        <p>
          BuildWise is a Vietnam / VND catalog builder. Choose components yourself to check compatibility and power, or
          ask the engine for a budget-aware recommendation. The page never invents sockets, wattage, or scores.
        </p>
      </section>

      <section className={styles.feature} aria-labelledby="start-build-heading">
        <h2 id="start-build-heading">Start your build</h2>
        <p className={styles.lede}>
          Pick one part per category from a persisted catalog. The backend reports whether those parts are compatible
          and whether the PSU has enough headroom.
        </p>
        <p className={styles.featureActions}>
          <Link className={styles.cta} href="/build">
            Open the parts table
          </Link>
        </p>
      </section>

      <section className={styles.feature} aria-labelledby="recommend-heading">
        <h2 id="recommend-heading">Get a recommended build</h2>
        <p className={styles.lede}>
          Prefer to start from a VND budget and workload? The same catalog can search for feasible builds and return
          ranked evidence.
        </p>
        <p className={styles.featureActions}>
          <Link className={styles.ctaSecondary} href="/recommend">
            Find a recommended build
          </Link>
        </p>
      </section>
    </main>
  );
}