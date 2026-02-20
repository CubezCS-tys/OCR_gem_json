"use client";

import { useEffect } from "react";
import dynamic from "next/dynamic";
import { useViewerStore } from "@/lib/store";
import { useScrollSync } from "@/hooks/useScrollSync";
import ViewerToolbar from "./ViewerToolbar";
import HtmlPanel from "./HtmlPanel";
import { Loader2 } from "lucide-react";

const PdfPanel = dynamic(() => import("./PdfPanel"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full bg-gray-200">
      <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
    </div>
  ),
});

const SearchablePdfPanel = dynamic(() => import("./SearchablePdfPanel"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full bg-gray-200">
      <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
    </div>
  ),
});

interface ViewerShellProps {
  docId: string;
}

export default function ViewerShell({ docId }: ViewerShellProps) {
  const { syncScroll, viewMode, rightPanelMode, currentPage, totalPages, setCurrentPage } =
    useViewerStore();
  const { leftRef, rightRef, handleLeftScroll, handleRightScroll } =
    useScrollSync(syncScroll);

  // Keyboard shortcuts
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Don't capture when typing in an input
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      )
        return;

      const { pdfZoom, htmlZoom, setPdfZoom, setHtmlZoom } =
        useViewerStore.getState();

      switch (e.key) {
        case "ArrowLeft":
          e.preventDefault();
          setCurrentPage(Math.max(1, currentPage - 1));
          break;
        case "ArrowRight":
          e.preventDefault();
          setCurrentPage(Math.min(totalPages, currentPage + 1));
          break;
        case "=":
        case "+":
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            setPdfZoom(pdfZoom + 25);
            setHtmlZoom(htmlZoom + 25);
          }
          break;
        case "-":
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            setPdfZoom(pdfZoom - 25);
            setHtmlZoom(htmlZoom - 25);
          }
          break;
        case "0":
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            setPdfZoom(150);
            setHtmlZoom(50);
          }
          break;
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [currentPage, totalPages, setCurrentPage]);

  // Reset state when docId changes
  useEffect(() => {
    useViewerStore.setState({
      currentPage: 1,
      pdfZoom: 150,
      htmlZoom: 50,
      viewMode: "continuous",
    });
  }, [docId]);

  return (
    <div className="flex flex-col h-screen">
      <ViewerToolbar docId={docId} />
      <div className="flex-1 grid grid-cols-2 min-h-0">
        <div className="border-r border-[var(--border)] min-h-0">
          <PdfPanel
            docId={docId}
            ref={leftRef}
            onScroll={handleLeftScroll}
          />
        </div>
        <div className="min-h-0">
          {rightPanelMode === "html" ? (
            <HtmlPanel
              docId={docId}
              ref={rightRef as React.RefObject<HTMLIFrameElement | null>}
              onIframeScroll={handleRightScroll}
            />
          ) : (
            <SearchablePdfPanel
              docId={docId}
              ref={rightRef as React.RefObject<HTMLDivElement | null>}
              onScroll={handleRightScroll}
            />
          )}
        </div>
      </div>
    </div>
  );
}
