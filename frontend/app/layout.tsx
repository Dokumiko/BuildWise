import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "AI-Assisted PC Configuration", description: "v0.1 catalog foundation" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="vi"><body>{children}</body></html>; }
