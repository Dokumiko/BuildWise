import type { Metadata } from "next";
import { IBM_Plex_Sans } from "next/font/google";
import { SiteShell } from "./site-shell";
import "./globals.css";

const sans = IBM_Plex_Sans({
  subsets: ["latin", "latin-ext", "vietnamese"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "BuildWise",
    template: "%s · BuildWise",
  },
  description: "Choose PC parts and inspect deterministic compatibility, power, and recommendation evidence for Vietnam.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="vi">
      <body className={sans.className}>
        <SiteShell>{children}</SiteShell>
      </body>
    </html>
  );
}