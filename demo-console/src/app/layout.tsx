import "./globals.css";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AIOps ChangeManagement · Demo Console",
  description:
    "AWS Seoul Summit 2026 — AI-Powered Cloud Ops 부스 데모 콘솔",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body className="bg-bg text-ink min-h-screen antialiased">{children}</body>
    </html>
  );
}
