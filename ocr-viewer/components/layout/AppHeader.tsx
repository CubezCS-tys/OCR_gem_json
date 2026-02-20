"use client";

import { FileText } from "lucide-react";
import Link from "next/link";

export default function AppHeader() {
  return (
    <header className="sticky top-0 z-50 border-b border-[var(--border)] bg-[var(--background)]/95 backdrop-blur">
      <div className="flex h-14 items-center gap-3 px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold text-lg">
          <FileText className="h-5 w-5 text-[var(--primary)]" />
          OCR Viewer
        </Link>
      </div>
    </header>
  );
}
