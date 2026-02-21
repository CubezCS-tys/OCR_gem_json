"use client";

import { useEffect, useState } from "react";
import { useViewerStore } from "@/lib/store";
import dynamic from "next/dynamic";

// Dynamically import react-pdf to avoid SSR issues and Node.js version conflicts
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
  const [numPages, setNumPages] = useState<number>(0);
  const [pageWidth, setPageWidth] = useState<number>(600);
  const [isClient, setIsClient] = useState(false);

  useEffect(() => {
    // Ensure we're on the client side
    setIsClient(true);
    
    // Configure PDF.js worker (only on client)
    if (typeof window !== "undefined") {
      import("react-pdf").then((pdfjs) => {
        pdfjs.pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.pdfjs.version}/build/pdf.worker.min.mjs`;
      });
    }

    // Calculate page width based on container size
    const updateWidth = () => {
      const container = document.getElementById("pdf-container");
      if (container) {
        setPageWidth(container.clientWidth - 40);
      }
    };

    updateWidth();
    window.addEventListener("resize", updateWidth);
    return () => window.removeEventListener("resize", updateWidth);
  }, []);

  const onDocumentLoadSuccess = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
  };

  if (!isClient) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (!currentFile?.pdfPath) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-muted-foreground">No PDF file available</p>
      </div>
    );
  }

  return (
    <div className="w-full bg-gray-100 dark:bg-gray-900">
      <div id="pdf-container" className="flex justify-center p-4">
        <Document
          file={`/api/pdf/${currentFile.name}`}
          onLoadSuccess={onDocumentLoadSuccess}
          loading={
            <div className="flex items-center justify-center p-8">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
            </div>
          }
          error={
            <div className="flex items-center justify-center p-8">
              <p className="text-destructive">Failed to load PDF</p>
            </div>
          }
        >
          <Page
            pageNumber={currentPage}
            width={pageWidth}
            renderTextLayer={true}
            renderAnnotationLayer={true}
            className="shadow-lg"
          />
        </Document>
      </div>
    </div>
  );
}
