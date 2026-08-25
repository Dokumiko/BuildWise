import type { Metadata } from "next";
import { IBM_Plex_Sans } from "next/font/google";
import "./globals.css";

const sans = IBM_Plex_Sans({
  subsets: ["latin", "latin-ext", "vietnamese"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "BuildWise",
  description: "Choose PC parts and inspect deterministic compatibility, power, and recommendation evidence for Vietnam.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="vi">
      <body className={sans.className}>
        <div
          hidden
          dangerouslySetInnerHTML={{
            __html: "<!-- THESIS: Manual part picking is the first job; recommendation is secondary. The page refuses a recommendation-first homepage. OWN-WORLD: Dark catalog surface, IBM Plex Sans, mint evidence accent, tabular prices. STORY: A builder picks parts, then sees backend compatibility. FIRST VIEWPORT: Brief intro, then the parts table, then recommendation. FORM: PC-builder catalog table. FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance -->",
          }}
        />
        {children}
      </body>
    </html>
  );
}