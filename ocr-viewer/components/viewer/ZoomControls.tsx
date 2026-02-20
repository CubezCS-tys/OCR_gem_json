"use client";

import { ZoomIn, ZoomOut, RotateCcw } from "lucide-react";

interface ZoomControlsProps {
  zoom: number;
  onZoomChange: (zoom: number) => void;
}

export default function ZoomControls({ zoom, onZoomChange }: ZoomControlsProps) {
  return (
    <div className="flex items-center gap-1">
      <button
        onClick={() => onZoomChange(zoom - 25)}
        className="rounded p-1 hover:bg-[var(--accent)] text-[var(--muted-foreground)]"
        title="Zoom out"
      >
        <ZoomOut className="h-3.5 w-3.5" />
      </button>
      <span className="min-w-[3rem] text-center text-xs tabular-nums text-[var(--muted-foreground)]">
        {zoom}%
      </span>
      <button
        onClick={() => onZoomChange(zoom + 25)}
        className="rounded p-1 hover:bg-[var(--accent)] text-[var(--muted-foreground)]"
        title="Zoom in"
      >
        <ZoomIn className="h-3.5 w-3.5" />
      </button>
      <button
        onClick={() => onZoomChange(100)}
        className="rounded p-1 hover:bg-[var(--accent)] text-[var(--muted-foreground)]"
        title="Reset zoom"
      >
        <RotateCcw className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
