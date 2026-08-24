import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "BuildWise · PC Recommendation",
  description: "Evidence-backed deterministic PC build recommendations for Vietnam.",
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="vi"><body>{children}</body></html>; }
