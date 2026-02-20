"use client";

import { useEffect, useRef, useState, forwardRef, useCallback } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import PanelHeader from "./PanelHeader";
import ZoomControls from "./ZoomControls";
import { useViewerStore } from "@/lib/store";
import { Loader2 } from "lucide-react";

pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

interface PdfPanelProps {
  docId: string;
  onScroll?: () => void;
}

const PdfPanel = forwardRef<HTMLDivElement, PdfPanelProps>(function PdfPanel(
  { docId, onScroll },
  ref
) {
  const { viewMode, currentPage, setTotalPages, pdfZoom, setPdfZoom } =
    useViewerStore();
  const [numPages, setNumPages] = useState(0);
  const [visiblePages, setVisiblePages] = useState<Set<number>>(new Set([1, 2]));
  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const containerRef = useRef<HTMLDivElement>(null);

  // Merge forwarded ref with local ref
  const setRefs = useCallback(
    (node: HTMLDivElement | null) => {
      (containerRef as React.MutableRefObject<HTMLDivElement | null>).current = node;
      if (typeof ref === "function") ref(node);
      else if (ref) (ref as React.MutableRefObject<HTMLDivElement | null>).current = node;
    },
    [ref]
  );

  function onDocumentLoadSuccess({ numPages: n }: { numPages: number }) {
    setNumPages(n);
    setTotalPages(n);
  }

  // Intersection observer for lazy rendering in continuous mode
  useEffect(() => {
    if (viewMode !== "continuous" || numPages === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        setVisiblePages((prev) => {
          const next = new Set(prev);
          for (const entry of entries) {
            const pageNum = Number(entry.target.getAttribute("data-page"));
            if (entry.isIntersecting) {
              next.add(pageNum);
              // Also preload adjacent pages
              if (pageNum > 1) next.add(pageNum - 1);
              if (pageNum < numPages) next.add(pageNum + 1);
            }
          }
          return next;
        });
      },
      {
        root: containerRef.current,
        rootMargin: "200px",
        threshold: 0,
      }
    );

    for (const [, el] of pageRefs.current) {
      observer.observe(el);
    }

    return () => observer.disconnect();
  }, [viewMode, numPages]);

  // Scroll to page in continuous mode
  useEffect(() => {
    if (viewMode !== "continuous") return;
    const el = pageRefs.current.get(currentPage);
    if (el && containerRef.current) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [currentPage, viewMode]);

  const scale = pdfZoom / 100;

  return (
    <div className="flex flex-col h-full">
      <PanelHeader title="Original PDF">
        <ZoomControls zoom={pdfZoom} onZoomChange={setPdfZoom} />
      </PanelHeader>
      <div
        ref={setRefs}
        className="flex-1 overflow-auto bg-gray-200"
        onScroll={onScroll}
      >
        <Document
          file={`/api/pdf/${docId}`}
          onLoadSuccess={onDocumentLoadSuccess}
          loading={
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
            </div>
          }
          error={
            <div className="py-20 text-center text-red-500">
              Failed to load PDF
            </div>
          }
        >
          {viewMode === "continuous"
            ? Array.from({ length: numPages }, (_, i) => {
                const pageNum = i + 1;
                return (
                  <div
                    key={pageNum}
                    data-page={pageNum}
                    ref={(el) => {
                      if (el) pageRefs.current.set(pageNum, el);
                    }}
                    className="flex justify-center py-2"
                  >
                    {visiblePages.has(pageNum) ? (
                      <Page
                        pageNumber={pageNum}
                        scale={scale}
                        devicePixelRatio={window.devicePixelRatio || 1}
                        loading={
                          <div className="flex h-[792px] w-[612px] items-center justify-center bg-white shadow">
                            <Loader2 className="h-6 w-6 animate-spin text-gray-300" />
                          </div>
                        }
                      />
                    ) : (
                      <div
                        className="bg-white shadow"
                        style={{
                          width: 612 * scale,
                          height: 792 * scale,
                        }}
                      />
                    )}
                  </div>
                );
              })
            : // Single page mode
              numPages > 0 && (
                <div className="flex justify-center py-4">
                  <Page
                    pageNumber={currentPage}
                    scale={scale}
                    devicePixelRatio={window.devicePixelRatio || 1}
                    loading={
                      <div className="flex h-[792px] w-[612px] items-center justify-center bg-white shadow">
                        <Loader2 className="h-6 w-6 animate-spin text-gray-300" />
                      </div>
                    }
                  />
                </div>
              )}
        </Document>
      </div>
    </div>
  );
});

export default PdfPanel;
