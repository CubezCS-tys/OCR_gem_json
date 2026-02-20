"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { useViewerStore } from "@/lib/store";
import ViewModeToggle from "./ViewModeToggle";
import PageNavigator from "./PageNavigator";
import SyncScrollToggle from "./SyncScrollToggle";
import RightPanelToggle from "./RightPanelToggle";

interface ViewerToolbarProps {
  docId: string;
}

export default function ViewerToolbar({ docId }: ViewerToolbarProps) {
  const {
    viewMode,
    setViewMode,
    rightPanelMode,
    setRightPanelMode,
    currentPage,
    totalPages,
    setCurrentPage,
    syncScroll,
    setSyncScroll,
  } = useViewerStore();

  return (
    <div className="flex h-12 items-center gap-4 border-b border-[var(--border)] bg-[var(--background)] px-4">
      <Link
        href="/"
        className="flex items-center gap-1.5 rounded-md px-2 py-1 text-sm text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
      >
        <ArrowLeft className="h-4 w-4" />
        Back
      </Link>

      <div className="h-5 w-px bg-[var(--border)]" />

      <span className="font-mono text-sm font-medium">{docId}</span>

      <div className="flex-1" />

      <ViewModeToggle mode={viewMode} onChange={setViewMode} />

      <PageNavigator
        currentPage={currentPage}
        totalPages={totalPages}
        onPageChange={setCurrentPage}
      />

      <RightPanelToggle mode={rightPanelMode} onChange={setRightPanelMode} />

      <SyncScrollToggle synced={syncScroll} onToggle={setSyncScroll} />
    </div>
  );
}
