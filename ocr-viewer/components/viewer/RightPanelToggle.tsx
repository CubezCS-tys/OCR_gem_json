"use client";

import { FileText, FileSearch } from "lucide-react";
import type { RightPanelMode } from "@/lib/types";

interface RightPanelToggleProps {
  mode: RightPanelMode;
  onChange: (mode: RightPanelMode) => void;
}

export default function RightPanelToggle({ mode, onChange }: RightPanelToggleProps) {
  return (
    <div className="flex items-center rounded-md border border-[var(--border)] bg-[var(--background)]">
      <button
        onClick={() => onChange("html")}
        className={`flex items-center gap-1.5 rounded-l-md px-2.5 py-1 text-xs transition-colors ${
          mode === "html"
            ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
            : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
        }`}
        title="OCR HTML overlay"
      >
        <FileText className="h-3.5 w-3.5" />
        HTML
      </button>
      <button
        onClick={() => onChange("searchable-pdf")}
        className={`flex items-center gap-1.5 rounded-r-md px-2.5 py-1 text-xs transition-colors ${
          mode === "searchable-pdf"
            ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
            : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
        }`}
        title="Searchable PDF"
      >
        <FileSearch className="h-3.5 w-3.5" />
        Searchable PDF
      </button>
    </div>
  );
}
