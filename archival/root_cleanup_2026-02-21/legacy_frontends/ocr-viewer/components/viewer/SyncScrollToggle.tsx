"use client";

import { Link2, Link2Off } from "lucide-react";

interface SyncScrollToggleProps {
  synced: boolean;
  onToggle: (synced: boolean) => void;
}

export default function SyncScrollToggle({ synced, onToggle }: SyncScrollToggleProps) {
  return (
    <button
      onClick={() => onToggle(!synced)}
      className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition-colors ${
        synced
          ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
          : "border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
      }`}
      title={synced ? "Disable scroll sync" : "Enable scroll sync"}
    >
      {synced ? <Link2 className="h-3.5 w-3.5" /> : <Link2Off className="h-3.5 w-3.5" />}
      Sync
    </button>
  );
}
