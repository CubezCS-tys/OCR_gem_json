"use client";

import { useEffect, useState } from "react";
import { useViewerStore } from "@/lib/store";

export function HTMLPreview() {
  const { currentFile, currentPage, currentFolder } = useViewerStore();
  const [htmlContent, setHtmlContent] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (currentFile?.htmlPath) {
      loadHTMLContent();
    }
  }, [currentFile, currentPage, currentFolder]);

  const loadHTMLContent = async () => {
    if (!currentFile?.name) return;

    try {
      setLoading(true);
      const response = await fetch(`/api/html/${currentFile.name}?folder=${currentFolder}`);
      const html = await response.text();
      
      const pageHtml = extractPageHtml(html, currentPage);
      setHtmlContent(pageHtml);
    } catch (err) {
      console.error("Failed to load HTML:", err);
      setHtmlContent("<p style='color: red; padding: 20px;'>Failed to load HTML preview</p>");
    } finally {
      setLoading(false);
    }
  };

  const extractPageHtml = (fullHtml: string, pageNum: number): string => {
    const parser = new DOMParser();
    const doc = parser.parseFromString(fullHtml, 'text/html');
    const pageElement = doc.querySelector(`#page-${pageNum}`);
    
    if (!pageElement) {
      return `<div style="padding: 20px; color: #666;">Page ${pageNum} not found</div>`;
    }
    
    const headContent = doc.head.innerHTML;
    
    return `
      <!DOCTYPE html>
      <html dir="${doc.documentElement.getAttribute('dir') || 'ltr'}" lang="${doc.documentElement.getAttribute('lang') || 'en'}">
      <head>
        ${headContent}
        <style>
          body { margin: 0; padding: 20px; background: white; }
          .page { margin: 0 auto; max-width: 100%; }
        </style>
      </head>
      <body>
        ${pageElement.outerHTML}
      </body>
      </html>
    `;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  return (
    <div className="w-full h-full">
      <iframe
        srcDoc={htmlContent}
        className="w-full h-full border-0"
        style={{ transform: 'scale(1.15)', transformOrigin: 'top left', width: '87%', height: '87%' }}
        title="HTML Preview"
      />
    </div>
  );
}
