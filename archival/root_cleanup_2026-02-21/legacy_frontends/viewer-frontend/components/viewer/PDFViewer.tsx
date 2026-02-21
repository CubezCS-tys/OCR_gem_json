"use client";

import { useEffect, useState } from "react";
import { useViewerStore } from "@/lib/store";
import dynamic from "next/dynamic";
import { Button } from "@/components/ui/button";
import { ZoomIn, ZoomOut, RotateCcw } from "lucide-react";

const Document = dynamic(
  () => import("react-pdf").then((mod) => mod.Document),
  { ssr: false }
);
const Page = dynamic(
  () => import("react-pdf").then((mod) => mod.Page),
  { ssr: false }
);

export function PDFViewer() {
  const { currentFile, currentPage } = useViewerStore();
  const [pageWidth, setPageWidth] = useState<number>(500);
  const [zoom, setZoom] = useState<number>(1.0);
  const [isClient, setIsClient] = useState(false);
  
  // Ensure page number is valid
  const safePageNumber = isNaN(currentPage) || currentPage < 1 ? 1 : currentPage;

  useEffect(() => {
    setIsClient(true);
    
    if (typeof window !== "undefined") {
      import("react-pdf").then((pdfjs) => {
        pdfjs.pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.pdfjs.version}/build/pdf.worker.min.mjs`;
      });
    }

    const updateWidth = () => {
      const container = document.getElementById("pdf-container");
      if (container) {
        setPageWidth(Math.min(container.clientWidth - 64, 700));
      }
    };

    updateWidth();
    window.addEventListener("resize", updateWidth);
    return () => window.removeEventListener("resize", updateWidth);
  }, []);

  const handleZoomIn = () => setZoom((prev) => Math.min(prev + 0.2, 3.0));
  const handleZoomOut = () => setZoom((prev) => Math.max(prev - 0.2, 0.5));
  const handleResetZoom = () => setZoom(1.0);

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
    <div className="flex flex-col h-full">
      {/* Zoom Controls */}
      <div className="flex items-center justify-center gap-2 p-2 border-b bg-muted/30">
        <Button variant="outline" size="sm" onClick={handleZoomOut} disabled={zoom <= 0.5}>
          <ZoomOut className="h-4 w-4" />
        </Button>
        <span className="text-sm font-medium min-w-16 text-center">{Math.round(zoom * 100)}%</span>
        <Button variant="outline" size="sm" onClick={handleZoomIn} disabled={zoom >= 3.0}>
          <ZoomIn className="h-4 w-4" />
        </Button>
        <Button variant="outline" size="sm" onClick={handleResetZoom}>
          <RotateCcw className="h-4 w-4" />
        </Button>
      </div>

      {/* PDF Container */}
      <div id="pdf-container" className="flex-1 overflow-auto">
        <div className="flex justify-center p-6 min-h-full">
          <Document
            file={`/api/pdf/${currentFile.name}`}
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
            <Page
              pageNumber={safePageNumber}
              width={pageWidth * zoom}
              renderTextLayer={false}
              renderAnnotationLayer={false}
              className="shadow-2xl rounded-sm"
            />
          </Document>
        </div>
      </div>
    </div>
  );
}
