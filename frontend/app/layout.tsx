import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Teaching AI Agents · Operations",
  description: "Local acquisition research and audit console",
};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="en"><body>{children}</body></html>;
}
