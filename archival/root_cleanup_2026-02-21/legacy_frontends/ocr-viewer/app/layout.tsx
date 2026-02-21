import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OCR Document Viewer",
  description: "Side-by-side OCR document viewer",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
