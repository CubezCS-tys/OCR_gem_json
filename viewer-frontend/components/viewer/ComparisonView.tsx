"use client";

import { useRef, useState, useEffect } from "react";
import { useViewerStore } from "@/lib/store";
import { PDFViewer } from "./PDFViewer";
import { HTMLPreview } from "./HTMLPreview";
import { Button } from "@/components/ui/button";
import { Link2, Link2Off, SplitSquareHorizontal, Eye } from "lucide-react";
import { cn } from "@/lib/utils";

export function ComparisonView() {
  const { currentFile, documentData, splitRatio, setSplitRatio } = useViewerStore();
  const [syncScroll, setSyncScroll] = useState(true);
  const [overlayMode, setOverlayMode] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  const leftScrollRef = useRef<HTMLDivElement>(null);
  const rightScrollRef = useRef<HTMLDivElement>(null);
  const dividerRef = useRef<HTMLDivElement>(null);

  // Synchronized scrolling
  useEffect(() => {
    if (!syncScroll) return;

    const leftEl = leftScrollRef.current;
    const rightEl = rightScrollRef.current;
    if (!leftEl || !rightEl) return;

    const syncLeftToRight = () => {
      if (!leftEl || !rightEl) return;
      const scrollPercentage = leftEl.scrollTop / (leftEl.scrollHeight - leftEl.clientHeight);
      rightEl.scrollTop = scrollPercentage * (rightEl.scrollHeight - rightEl.clientHeight);
    };

    const syncRightToLeft = () => {
      if (!leftEl || !rightEl) return;
      const scrollPercentage = rightEl.scrollTop / (rightEl.scrollHeight - rightEl.clientHeight);
      leftEl.scrollTop = scrollPercentage * (leftEl.scrollHeight - leftEl.clientHeight);
    };

    leftEl.addEventListener('scroll', syncLeftToRight);
    rightEl.addEventListener('scroll', syncRightToLeft);

    return () => {
      leftEl.removeEventListener('scroll', syncLeftToRight);
      rightEl.removeEventListener('scroll', syncRightToLeft);
    };
  }, [syncScroll]);

  // Draggable divider
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging) return;
      const container = dividerRef.current?.parentElement;
      if (!container) return;

      const containerRect = container.getBoundingClientRect();
      const newRatio = ((e.clientX - containerRect.left) / containerRect.width) * 100;
      setSplitRatio(Math.max(20, Math.min(80, newRatio)));
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, setSplitRatio]);

  if (!currentFile || !documentData) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center max-w-md">
          <p className="text-lg text-muted-foreground mb-4">
            No document selected
          </p>
          <p className="text-sm text-muted-foreground">
            Click "Open File" to select a document to view
          </p>
        </div>
      </div>
    );
  }

  if (overlayMode) {
    return (
      <div className="relative h-full">
        {/* Toolbar */}
        <div className="absolute top-0 left-0 right-0 z-10 px-4 py-3 border-b bg-background/95 backdrop-blur">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">Overlay Comparison Mode</h3>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setOverlayMode(false)}
              >
                <SplitSquareHorizontal className="h-4 w-4 mr-2" />
                Split View
              </Button>
            </div>
          </div>
        </div>

        {/* Overlay Content */}
        <div className="pt-16 h-full">
          <div className="relative h-full">
            <div className="absolute inset-0 opacity-50">
              <PDFViewer />
            </div>
            <div className="absolute inset-0 opacity-50 mix-blend-multiply dark:mix-blend-screen">
              <HTMLPreview />
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
        <div className="flex items-center gap-4">
          <Button
            variant={syncScroll ? "default" : "outline"}
            size="sm"
            onClick={() => setSyncScroll(!syncScroll)}
            className="gap-2"
          >
            {syncScroll ? (
              <>
                <Link2 className="h-4 w-4" />
                Synced
              </>
            ) : (
              <>
                <Link2Off className="h-4 w-4" />
                Not Synced
              </>
            )}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setOverlayMode(true)}
            className="gap-2"
          >
            <Eye className="h-4 w-4" />
            Overlay Mode
          </Button>
        </div>
        <div className="text-xs text-muted-foreground">
          Drag the center divider to adjust split ratio
        </div>
      </div>

      {/* Split View */}
      <div className="flex h-[calc(100%-4rem)] relative">
        {/* Left: PDF */}
        <div
          className="flex flex-col overflow-hidden"
          style={{ width: `${splitRatio}%` }}
        >
          <div className="px-4 py-3 border-b bg-muted/30">
            <h3 className="text-sm font-semibold">Original PDF</h3>
          </div>
          <div
            ref={leftScrollRef}
            className="flex-1 overflow-y-auto bg-slate-50 dark:bg-slate-900"
          >
            <PDFViewer />
          </div>
        </div>

        {/* Draggable Divider */}
        <div
          ref={dividerRef}
          className={cn(
            "w-1 bg-border hover:bg-primary cursor-col-resize transition-colors relative group",
            isDragging && "bg-primary"
          )}
          onMouseDown={() => setIsDragging(true)}
        >
          <div className="absolute inset-y-0 -left-2 -right-2 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
            <div className="w-1 h-12 bg-primary rounded-full" />
          </div>
        </div>

        {/* Right: HTML */}
        <div
          className="flex flex-col overflow-hidden"
          style={{ width: `${100 - splitRatio}%` }}
        >
          <div className="px-4 py-3 border-b bg-muted/30">
            <h3 className="text-sm font-semibold">Generated HTML</h3>
          </div>
          <div ref={rightScrollRef} className="flex-1 overflow-y-auto">
            <HTMLPreview />
          </div>
        </div>
      </div>

      {/* Quick Split Ratio Buttons */}
      <div className="absolute bottom-4 left-1/2 transform -translate-x-1/2 flex gap-1 bg-background/95 backdrop-blur border rounded-lg p-1 shadow-lg">
        <Button
          variant={splitRatio === 30 ? "default" : "ghost"}
          size="sm"
          onClick={() => setSplitRatio(30)}
          className="text-xs"
        >
          30/70
        </Button>
        <Button
          variant={splitRatio === 50 ? "default" : "ghost"}
          size="sm"
          onClick={() => setSplitRatio(50)}
          className="text-xs"
        >
          50/50
        </Button>
        <Button
          variant={splitRatio === 70 ? "default" : "ghost"}
          size="sm"
          onClick={() => setSplitRatio(70)}
          className="text-xs"
        >
          70/30
        </Button>
      </div>
    </div>
  );
}
