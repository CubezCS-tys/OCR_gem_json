"use client";

import { useEffect, useState } from "react";
import { useViewerStore } from "@/lib/store";
import dynamic from "next/dynamic";

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
  const [pageWidth, setPageWidth] = useState<number>(600);
  const [isClient, setIsClient] = useState(false);

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
        setPageWidth(Math.min(container.clientWidth - 48, 900));
      }
    };

    updateWidth();
    window.addEventListener("resize", updateWidth);
    return () => window.removeEventListener("resize", updateWidth);
  }, []);

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
    <div id="pdf-container" className="flex justify-center p-6">
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
          pageNumber={currentPage}
          width={pageWidth}
          renderTextLayer={false}
          renderAnnotationLayer={false}
          className="shadow-2xl rounded-sm"
        />
      </Document>
    </div>
  );
}
