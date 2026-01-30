"use client";

import { useEffect, useState, useRef, useMemo } from "react";
import { useViewerStore } from "@/lib/store";
import { AlertCircle, Loader2, FileX } from "lucide-react";

// Cache for parsed HTML pages to avoid re-fetching
const htmlCache = new Map<string, string>();

export function HTMLPreview() {
  const { currentFile, currentPage, hasUnsavedChanges } = useViewerStore();
  const [htmlContent, setHtmlContent] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Generate cache key
  const cacheKey = useMemo(() => {
    if (!currentFile?.name) return '';
    // Include a timestamp suffix if there are unsaved changes to force refresh
    const suffix = hasUnsavedChanges ? '' : '-cached';
    return `${currentFile.name}-page-${currentPage}${suffix}`;
  }, [currentFile?.name, currentPage, hasUnsavedChanges]);

  useEffect(() => {
    if (currentFile?.htmlPath) {
      loadHTMLContent();
    }

    // Cleanup on unmount
    return () => {
      abortControllerRef.current?.abort();
    };
  }, [currentFile, currentPage]);

  const loadHTMLContent = async () => {
    if (!currentFile?.name) return;

    // Check cache first (only for non-edited content)
    if (!hasUnsavedChanges && htmlCache.has(cacheKey)) {
      setHtmlContent(htmlCache.get(cacheKey)!);
      setLoading(false);
      setError(null);
      return;
    }

    // Abort any previous request
    abortControllerRef.current?.abort();
    abortControllerRef.current = new AbortController();

    try {
      setLoading(true);
      setError(null);

      const response = await fetch(`/api/html/${currentFile.name}`, {
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const html = await response.text();

      // Extract only the current page from the HTML
      const pageHtml = extractPageHtml(html, currentPage);

      // Cache the result
      htmlCache.set(cacheKey, pageHtml);

      // Limit cache size to prevent memory issues
      if (htmlCache.size > 100) {
        const firstKey = htmlCache.keys().next().value;
        if (firstKey) htmlCache.delete(firstKey);
      }

      setHtmlContent(pageHtml);
      setError(null);
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        return; // Request was cancelled, ignore
      }
      console.error("Failed to load HTML:", err);
      setError(err instanceof Error ? err.message : "Failed to load HTML preview");
      setHtmlContent("");
    } finally {
      setLoading(false);
    }
  };

  const extractPageHtml = (fullHtml: string, pageNum: number): string => {
    try {
      // Create a temporary DOM to parse the HTML
      const parser = new DOMParser();
      const doc = parser.parseFromString(fullHtml, 'text/html');

      // Find the page element by id (e.g., id="page-1")
      const pageElement = doc.querySelector(`#page-${pageNum}`);

      if (!pageElement) {
        // Try alternative patterns
        const altPatterns = [
          `[data-page="${pageNum}"]`,
          `.page-${pageNum}`,
          `.page:nth-child(${pageNum})`,
        ];

        for (const pattern of altPatterns) {
          const altElement = doc.querySelector(pattern);
          if (altElement) {
            return buildPageHtml(doc, altElement.outerHTML);
          }
        }

        return `
          <div style="padding: 40px; text-align: center; color: #666;">
            <h3>Page ${pageNum} not found</h3>
            <p>This page may not exist in the HTML document.</p>
          </div>
        `;
      }

      return buildPageHtml(doc, pageElement.outerHTML);
    } catch (err) {
      console.error("Error extracting page HTML:", err);
      return `<div style="padding: 20px; color: red;">Error parsing HTML content</div>`;
    }
  };

  const buildPageHtml = (doc: Document, pageContent: string): string => {
    // Get the head content (styles, MathJax config, etc.)
    const headContent = doc.head.innerHTML;
    const dir = doc.documentElement.getAttribute('dir') || 'ltr';
    const lang = doc.documentElement.getAttribute('lang') || 'en';

    return `
      <!DOCTYPE html>
      <html dir="${dir}" lang="${lang}">
      <head>
        ${headContent}
        <style>
          html, body { 
            margin: 0; 
            padding: 0;
            background: white;
            min-height: 100%;
          }
          body { 
            padding: 20px; 
            box-sizing: border-box;
          }
          .page { 
            margin: 0 auto; 
            max-width: 100%;
          }
          /* Ensure RTL text is properly styled */
          [dir="rtl"], .rtl {
            direction: rtl;
            text-align: right;
          }
          /* Better equation rendering */
          mjx-container {
            overflow-x: auto;
            padding: 4px 0;
          }
        </style>
        <script>
          // MathJax initialization helpers
          function initMathJax() {
            if (window.MathJax && MathJax.typesetPromise) {
              MathJax.typesetPromise()
                .then(() => console.log('MathJax: Typesetting complete'))
                .catch((err) => console.error('MathJax error:', err));
            } else if (window.MathJax && MathJax.Hub) {
              MathJax.Hub.Queue(['Typeset', MathJax.Hub]);
            }
          }
          
          // Multiple trigger points for reliability
          window.addEventListener('load', () => setTimeout(initMathJax, 100));
          document.addEventListener('DOMContentLoaded', () => setTimeout(initMathJax, 200));
          
          // Fallback for slow loading
          setTimeout(initMathJax, 1000);
        </script>
      </head>
      <body>
        ${pageContent}
      </body>
      </html>
    `;
  };

  // Force refresh function for when HTML is regenerated
  const forceRefresh = () => {
    // Clear this page from cache
    htmlCache.delete(cacheKey);
    loadHTMLContent();
  };

  // Expose refresh function via ref
  useEffect(() => {
    const handleRefresh = () => forceRefresh();
    window.addEventListener('htmlPreviewRefresh', handleRefresh);
    return () => window.removeEventListener('htmlPreviewRefresh', handleRefresh);
  }, [cacheKey]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full bg-white dark:bg-gray-900">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">Loading HTML preview...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full bg-white dark:bg-gray-900">
        <div className="text-center p-4">
          <AlertCircle className="h-8 w-8 text-destructive mx-auto mb-2" />
          <p className="text-sm text-destructive mb-2">Failed to load preview</p>
          <p className="text-xs text-muted-foreground">{error}</p>
          <button
            onClick={forceRefresh}
            className="mt-4 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded hover:bg-primary/90"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!currentFile?.htmlPath) {
    return (
      <div className="flex items-center justify-center h-full bg-white dark:bg-gray-900">
        <div className="text-center p-4">
          <FileX className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">No HTML file available</p>
          <p className="text-xs text-muted-foreground mt-1">
            Save your changes to generate on HTML file
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full w-full bg-white dark:bg-gray-900">
      <iframe
        ref={iframeRef}
        srcDoc={htmlContent}
        className="w-full h-full border-0"
        sandbox="allow-same-origin allow-scripts"
        title={`HTML Preview - Page ${currentPage}`}
      />
    </div>
  );
}
