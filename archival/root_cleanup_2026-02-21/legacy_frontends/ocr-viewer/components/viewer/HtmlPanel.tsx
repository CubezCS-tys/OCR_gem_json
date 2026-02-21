"use client";

import { forwardRef, useCallback, useEffect, useRef } from "react";
import PanelHeader from "./PanelHeader";
import ZoomControls from "./ZoomControls";
import { useViewerStore } from "@/lib/store";
import { Loader2 } from "lucide-react";

interface HtmlPanelProps {
  docId: string;
  onIframeScroll?: () => void;
}

const HtmlPanel = forwardRef<HTMLIFrameElement, HtmlPanelProps>(
  function HtmlPanel({ docId, onIframeScroll }, ref) {
    const { viewMode, currentPage, htmlZoom, setHtmlZoom } = useViewerStore();
    const iframeRef = useRef<HTMLIFrameElement>(null);
    const loadedRef = useRef(false);

    // Merge refs
    const setRefs = useCallback(
      (node: HTMLIFrameElement | null) => {
        (iframeRef as React.MutableRefObject<HTMLIFrameElement | null>).current = node;
        if (typeof ref === "function") ref(node);
        else if (ref) (ref as React.MutableRefObject<HTMLIFrameElement | null>).current = node;
      },
      [ref]
    );

    const src =
      viewMode === "continuous"
        ? `/api/html/${docId}`
        : `/api/html/${docId}/${currentPage - 1}`;

    // Handle iframe load: hide toolbar, apply zoom, attach scroll listener
    const handleLoad = useCallback(() => {
      const iframe = iframeRef.current;
      if (!iframe) return;
      loadedRef.current = true;

      try {
        const doc = iframe.contentDocument;
        if (!doc) return;

        // Hide the built-in toolbar
        const toolbar = doc.querySelector(".toolbar") as HTMLElement;
        if (toolbar) toolbar.style.display = "none";

        // Remove toolbar top-margin from body
        doc.body.style.paddingTop = "0";

        // Apply zoom
        (doc.body.style as unknown as Record<string, string>).zoom = `${htmlZoom / 100}`;

        // Attach scroll handler for sync
        if (onIframeScroll) {
          doc.addEventListener("scroll", onIframeScroll);
        }
      } catch {
        // Cross-origin might block access (shouldn't happen since same-origin API)
      }
    }, [htmlZoom, onIframeScroll]);

    // Update zoom when it changes
    useEffect(() => {
      const iframe = iframeRef.current;
      if (!iframe || !loadedRef.current) return;
      try {
        const doc = iframe.contentDocument;
        if (doc) {
          (doc.body.style as unknown as Record<string, string>).zoom = `${htmlZoom / 100}`;
        }
      } catch {
        // Ignore
      }
    }, [htmlZoom]);

    return (
      <div className="flex flex-col h-full">
        <PanelHeader title="OCR Output">
          <ZoomControls zoom={htmlZoom} onZoomChange={setHtmlZoom} />
        </PanelHeader>
        <div className="flex-1 relative bg-gray-200">
          {!loadedRef.current && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
            </div>
          )}
          <iframe
            ref={setRefs}
            key={src}
            src={src}
            onLoad={handleLoad}
            className="w-full h-full border-0"
            title="OCR HTML Output"
          />
        </div>
      </div>
    );
  }
);

export default HtmlPanel;
