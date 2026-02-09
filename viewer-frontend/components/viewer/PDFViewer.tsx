"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useViewerStore } from "@/lib/store";
import dynamic from "next/dynamic";
import { Button } from "@/components/ui/button";
import {
  ZoomIn,
  ZoomOut,
  RotateCw,
  Maximize2,
  Minimize2,
  Maximize,
  Layers,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const Document = dynamic(
  () => import("react-pdf").then((mod) => mod.Document),
  { ssr: false }
);
const Page = dynamic(
  () => import("react-pdf").then((mod) => mod.Page),
  { ssr: false }
);

export function PDFViewer() {
  const {
    currentFile,
    currentPage,
    pdfZoom,
    setPdfZoom,
    pdfRotation,
    setPdfRotation,
    pdfFitMode,
    setPdfFitMode,
    isFullscreen,
    toggleFullscreen,
    nextPage,
    previousPage,
    goToPage,
    documentData,
  } = useViewerStore();

  const [pageWidth, setPageWidth] = useState<number>(500);
  const [isClient, setIsClient] = useState(false);
  const [numPages, setNumPages] = useState<number>(0);
  const [showThumbnails, setShowThumbnails] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Ensure page number is valid
  const safePageNumber = isNaN(currentPage) || currentPage < 1 ? 1 : currentPage;

  useEffect(() => {
    setIsClient(true);

    if (typeof window !== "undefined") {
      import("react-pdf").then((pdfjs) => {
        pdfjs.pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.pdfjs.version}/build/pdf.worker.min.mjs`;
      });
    }

    updateWidth();
    window.addEventListener("resize", updateWidth);
    return () => window.removeEventListener("resize", updateWidth);
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger if user is typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }

      switch (e.key) {
        case "ArrowLeft":
        case "ArrowUp":
          e.preventDefault();
          previousPage();
          break;
        case "ArrowRight":
        case "ArrowDown":
          e.preventDefault();
          nextPage();
          break;
        case "Home":
          e.preventDefault();
          goToPage(1);
          break;
        case "End":
          e.preventDefault();
          if (numPages) goToPage(numPages);
          break;
        case "+":
        case "=":
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            handleZoomIn();
          }
          break;
        case "-":
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            handleZoomOut();
          }
          break;
        case "0":
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            handleResetZoom();
          }
          break;
        case "f":
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            toggleFullscreen();
          }
          break;
        case "r":
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            handleRotate();
          }
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [nextPage, previousPage, goToPage, numPages, toggleFullscreen]);

  const updateWidth = useCallback(() => {
    if (containerRef.current) {
      const container = containerRef.current;
      setPageWidth(Math.min(container.clientWidth - 64, 800));
    }
  }, []);

  const handleZoomIn = () => setPdfZoom(pdfZoom + 0.2);
  const handleZoomOut = () => setPdfZoom(pdfZoom - 0.2);
  const handleResetZoom = () => {
    setPdfZoom(1.0);
    setPdfFitMode('custom');
  };
  const handleRotate = () => setPdfRotation(pdfRotation + 90);

  const handleFitModeChange = (mode: 'width' | 'page' | 'custom') => {
    setPdfFitMode(mode);
    if (mode === 'width') {
      setPdfZoom(1.0);
    } else if (mode === 'page') {
      setPdfZoom(0.85);
    }
  };

  const getEffectiveWidth = () => {
    if (pdfFitMode === 'width') {
      return pageWidth;
    } else if (pdfFitMode === 'page') {
      return pageWidth * 0.85;
    }
    return pageWidth * pdfZoom;
  };

  if (!isClient) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (!currentFile?.pdfPath) {
    return (
      <div className="flex items-center justify-center p-8 text-muted-foreground">
        No PDF selected
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col h-full", isFullscreen && "fixed inset-0 z-50 bg-background")}>
      {/* Enhanced Toolbar */}
      <div className="flex items-center justify-between gap-2 p-2 border-b bg-muted/30 flex-wrap">
        {/* Zoom Controls */}
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleZoomOut}
            disabled={pdfZoom <= 0.5}
            title="Zoom Out (Ctrl+-)"
          >
            <ZoomOut className="h-4 w-4" />
          </Button>
          <span className="text-sm font-medium min-w-16 text-center">
            {Math.round(pdfZoom * 100)}%
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={handleZoomIn}
            disabled={pdfZoom >= 3.0}
            title="Zoom In (Ctrl++)"
          >
            <ZoomIn className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleResetZoom}
            title="Reset Zoom (Ctrl+0)"
          >
            <Maximize className="h-4 w-4" />
          </Button>
        </div>

        {/* Fit Mode */}
        <Select value={pdfFitMode} onValueChange={(v) => handleFitModeChange(v as any)}>
          <SelectTrigger className="w-32 h-8">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="width">Fit Width</SelectItem>
            <SelectItem value="page">Fit Page</SelectItem>
            <SelectItem value="custom">Custom</SelectItem>
          </SelectContent>
        </Select>

        {/* Rotation & View Controls */}
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleRotate}
            title="Rotate (Ctrl+R)"
          >
            <RotateCw className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowThumbnails(!showThumbnails)}
            title="Toggle Thumbnails"
          >
            <Layers className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={toggleFullscreen}
            title="Fullscreen (Ctrl+F)"
          >
            {isFullscreen ? (
              <Minimize2 className="h-4 w-4" />
            ) : (
              <Maximize2 className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>

      {/* PDF Container with optional thumbnails */}
      <div className="flex flex-1 overflow-hidden">
        {/* Thumbnail Sidebar */}
        {showThumbnails && numPages > 0 && (
          <div className="w-32 border-r overflow-y-auto bg-muted/20 p-2 space-y-2">
            {Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => (
              <button
                key={pageNum}
                onClick={() => goToPage(pageNum)}
                className={cn(
                  "w-full border-2 rounded p-1 transition-all",
                  pageNum === safePageNumber
                    ? "border-primary bg-primary/10"
                    : "border-transparent hover:border-muted-foreground/30"
                )}
              >
                <div className="text-xs font-medium mb-1">Page {pageNum}</div>
                <div className="bg-white rounded overflow-hidden">
                  <Document
                    file={`/api/pdf/${currentFile.name}`}
                    loading={<div className="h-20 bg-muted animate-pulse" />}
                  >
                    <Page
                      pageNumber={pageNum}
                      width={100}
                      renderTextLayer={false}
                      renderAnnotationLayer={false}
                    />
                  </Document>
                </div>
              </button>
            ))}
          </div>
        )}

        {/* Main PDF View */}
        <div ref={containerRef} className="flex-1 overflow-auto">
          <div className="flex justify-center p-6 min-h-full">
            <Document
              file={`/api/pdf/${currentFile.name}`}
              onLoadSuccess={({ numPages }) => setNumPages(numPages)}
              loading={
                <div className="flex items-center justify-center p-8">
                  <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
                </div>
              }
              error={
                <div className="flex items-center justify-center p-8 text-destructive">
                  Failed to load PDF
                </div>
              }
            >
              <div style={{ transform: `rotate(${pdfRotation}deg)` }}>
                <Page
                  pageNumber={safePageNumber}
                  width={getEffectiveWidth()}
                  renderTextLayer={false}
                  renderAnnotationLayer={false}
                  className="shadow-2xl rounded-sm"
                />
              </div>
            </Document>
          </div>
        </div>
      </div>

      {/* Help Hint */}
      <div className="px-4 py-2 border-t bg-muted/20 text-xs text-muted-foreground">
        <span className="font-medium">Shortcuts:</span> ← → Navigate | Ctrl++ Zoom In | Ctrl+- Zoom Out | Ctrl+R Rotate | Ctrl+F Fullscreen
      </div>
    </div>
  );
}
