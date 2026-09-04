import type { Metadata } from "next";
import { IBM_Plex_Sans } from "next/font/google";
import { SiteShell } from "./site-shell";
import { BuildStateProvider } from "./build-state";
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
  description: "Chọn linh kiện PC và xem kết quả tương thích, điện năng và gợi ý cấu hình dành cho thị trường Việt Nam.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="vi">
      <body className={sans.className}>
        <BuildStateProvider><SiteShell>{children}</SiteShell></BuildStateProvider>
      </body>
    </html>
  );
}
