"use client";

import { useEffect, useState } from "react";
import { useViewerStore } from "@/lib/store";
import { FileX } from "lucide-react";

export function HTMLPreview() {
  const { currentFile, currentPage, currentFolder } = useViewerStore();
  const [htmlContent, setHtmlContent] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [debugInfo, setDebugInfo] = useState<string>("");

  useEffect(() => {
    console.log("HTMLPreview mounted/updated", {
      currentFile,
      currentPage,
      currentFolder,
      hasHtmlPath: !!currentFile?.htmlPath
    });

    if (currentFile?.htmlPath) {
      loadHTMLContent();
    } else {
      setLoading(false);
      console.warn("No htmlPath for current file");
    }
  }, [currentFile, currentPage, currentFolder]);

  const loadHTMLContent = async () => {
    if (!currentFile?.name) {
      console.error("No currentFile.name");
      return;
    }

    try {
      setLoading(true);
      setError("");

      const url = `/api/html/${currentFile.name}?folder=${currentFolder}`;
      console.log(`🔍 Fetching HTML from: ${url}`);

      const response = await fetch(url);
      console.log(`📡 Response status: ${response.status} ${response.statusText}`);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const html = await response.text();
      console.log(`✅ HTML loaded successfully, length: ${html.length} bytes`);
      console.log(`📄 First 200 chars:`, html.substring(0, 200));

      const pageHtml = extractPageHtml(html, currentPage);
      console.log(`📋 Extracted page HTML length: ${pageHtml.length} bytes`);

      setHtmlContent(pageHtml);
      setDebugInfo(`Loaded ${html.length} bytes, extracted page ${currentPage}`);
    } catch (err) {
      console.error("❌ Failed to load HTML:", err);
      const errorMsg = err instanceof Error ? err.message : "Unknown error";
      setError(errorMsg);
      setDebugInfo(`Error: ${errorMsg}`);
    } finally {
      setLoading(false);
    }
  };

  const extractPageHtml = (fullHtml: string, pageNum: number): string => {
    console.log(`🔍 Extracting page ${pageNum} from HTML`);

    const parser = new DOMParser();
    const doc = parser.parseFromString(fullHtml, 'text/html');
    const pageElement = doc.querySelector(`#page-${pageNum}`);

    if (!pageElement) {
      console.warn(`⚠️ Page element #page-${pageNum} not found`);
      const allPages = doc.querySelectorAll('[id^="page-"]');
      const pageIds = Array.from(allPages).map(p => p.id);
      console.log("Available pages:", pageIds);

      if (allPages.length === 0) {
        console.log("No page elements found, returning full HTML");
        return fullHtml;
      }

      return `<html><body style="padding: 20px; font-family: sans-serif;">
        <h3>⚠️ Page ${pageNum} not found</h3>
        <p>Available pages: ${pageIds.join(', ')}</p>
      </body></html>`;
    }

    console.log(`✅ Found page element #page-${pageNum}`);

    const headContent = doc.head.innerHTML;

    const extractedHtml = `<!DOCTYPE html>
<html dir="${doc.documentElement.getAttribute('dir') || 'ltr'}" lang="${doc.documentElement.getAttribute('lang') || 'en'}">
<head>
  <meta charset="UTF-8">
  ${headContent}
  <style>
    body {
      margin: 0;
      padding: 20px;
      background: white;
      overflow: auto;
    }
    .page {
      margin: 0 auto;
      max-width: 100%;
    }
  </style>
</head>
<body>
  ${pageElement.outerHTML}
</body>
</html>`;

    console.log(`📝 Final HTML length: ${extractedHtml.length} bytes`);
    return extractedHtml;
  };

  // No HTML file available for this document
  if (!currentFile?.htmlPath) {
    return (
      <div className="flex items-center justify-center h-full bg-slate-50 dark:bg-slate-900">
        <div className="text-center max-w-md p-8">
          <FileX className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
          <h3 className="text-lg font-semibold mb-2">No HTML Preview Available</h3>
          <p className="text-sm text-muted-foreground mb-4">
            This document doesn't have an HTML file in the <strong>{currentFolder}</strong> folder.
          </p>
          <p className="text-xs text-muted-foreground">
            Try selecting a document from:
          </p>
          <ul className="text-xs text-muted-foreground mt-2 space-y-1">
            <li>• <strong>batch_markdown2</strong> (5 files with HTML)</li>
            <li>• <strong>outputs</strong> (1 file with HTML)</li>
          </ul>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-white p-8">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mb-4"></div>
        <p className="text-muted-foreground">Loading HTML...</p>
        <p className="text-xs text-muted-foreground mt-2">
          {currentFile.name} - Page {currentPage}
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full bg-white p-8">
        <div className="text-center max-w-md">
          <p className="text-destructive mb-2">⚠️ Error: {error}</p>
          <p className="text-sm text-muted-foreground mb-2">Check browser console for details</p>
          <p className="text-xs text-muted-foreground">{debugInfo}</p>
        </div>
      </div>
    );
  }

  if (!htmlContent) {
    return (
      <div className="flex items-center justify-center h-full bg-white p-8">
        <div className="text-center">
          <p className="text-muted-foreground">No content loaded</p>
          <p className="text-xs text-muted-foreground mt-2">{debugInfo}</p>
        </div>
      </div>
    );
  }

  console.log("🎨 Rendering iframe with HTML content");

  return (
    <div className="w-full h-full bg-white relative">
      {/* Debug info overlay */}
      <div className="absolute top-2 left-2 z-10 bg-black/70 text-white text-xs px-2 py-1 rounded">
        Page {currentPage} | {htmlContent.length} bytes
      </div>

      <iframe
        srcDoc={htmlContent}
        className="w-full h-full border-0"
        title="HTML Preview"
        sandbox="allow-same-origin allow-scripts allow-popups allow-forms"
        onLoad={() => console.log("✅ iframe loaded successfully")}
        onError={(e) => console.error("❌ iframe error:", e)}
      />
    </div>
  );
}
