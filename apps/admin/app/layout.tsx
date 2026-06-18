import type { Metadata } from "next";
import Link from "next/link";
import { TenantBar } from "./TenantBar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cortex Admin",
  description: "Source management, process review, and search for Cortex.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav className="nav">
          <span className="brand">Cortex</span>
          <Link href="/sources">Sources</Link>
          <Link href="/processes">Processes</Link>
          <Link href="/search">Search</Link>
          <span className="spacer" />
          <TenantBar />
        </nav>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
