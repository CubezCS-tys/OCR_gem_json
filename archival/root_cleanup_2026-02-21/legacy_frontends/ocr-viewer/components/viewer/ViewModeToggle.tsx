"use client";

import { Rows3, Square } from "lucide-react";
import type { ViewMode } from "@/lib/types";

interface ViewModeToggleProps {
  mode: ViewMode;
  onChange: (mode: ViewMode) => void;
}

export default function ViewModeToggle({ mode, onChange }: ViewModeToggleProps) {
  return (
    <div className="flex items-center rounded-md border border-[var(--border)] bg-[var(--background)]">
      <button
        onClick={() => onChange("continuous")}
        className={`flex items-center gap-1.5 rounded-l-md px-2.5 py-1 text-xs transition-colors ${
          mode === "continuous"
            ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
            : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
        }`}
        title="Continuous scroll"
      >
        <Rows3 className="h-3.5 w-3.5" />
        Continuous
      </button>
      <button
        onClick={() => onChange("single")}
        className={`flex items-center gap-1.5 rounded-r-md px-2.5 py-1 text-xs transition-colors ${
          mode === "single"
            ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
            : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
        }`}
        title="Single page"
      >
        <Square className="h-3.5 w-3.5" />
        Single
      </button>
    </div>
  );
}
