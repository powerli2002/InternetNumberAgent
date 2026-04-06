import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Fusion Agent",
  description: "多用户 Agent 与 OpenSandbox 产品前端"
};

export default function RootLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
