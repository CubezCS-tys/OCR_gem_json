"use client";

import { useEffect, useState } from "react";
import { useViewerStore } from "@/lib/store";

export function HTMLPreview() {
  const { currentFile, currentPage } = useViewerStore();
  const [htmlContent, setHtmlContent] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (currentFile?.htmlPath) {
      loadHTMLContent();
    }
  }, [currentFile, currentPage]);

  const loadHTMLContent = async () => {
    if (!currentFile?.name) return;

    try {
      setLoading(true);
      const response = await fetch(`/api/html/${currentFile.name}`);
      const html = await response.text();
      
      // Extract only the current page from the HTML
      const pageHtml = extractPageHtml(html, currentPage);
      setHtmlContent(pageHtml);
    } catch (err) {
      console.error("Failed to load HTML:", err);
      setHtmlContent("<p style='color: red;'>Failed to load HTML preview</p>");
    } finally {
      setLoading(false);
    }
  };

  const extractPageHtml = (fullHtml: string, pageNum: number): string => {
    // Create a temporary DOM to parse the HTML
    const parser = new DOMParser();
    const doc = parser.parseFromString(fullHtml, 'text/html');
    
    // Find the page element by id (e.g., id="page-1")
    const pageElement = doc.querySelector(`#page-${pageNum}`);
    
    if (!pageElement) {
      return `<div style="padding: 20px; color: #666;">Page ${pageNum} not found in HTML</div>`;
    }
    
    // Get the head content (styles, etc.)
    const headContent = doc.head.innerHTML;
    
    // Create a new HTML document with just this page
    return `
      <!DOCTYPE html>
      <html dir="${doc.documentElement.getAttribute('dir') || 'ltr'}" lang="${doc.documentElement.getAttribute('lang') || 'en'}">
      <head>
        ${headContent}
        <style>
          body { margin: 0; padding: 20px; background: white; }
          .page { margin: 0 auto; max-width: 100%; }
        </style>
        <script>
          // Enhanced MathJax initialization for single page
          if (window.MathJax && MathJax.startup) {
            // Override the pageReady to ensure typesetting happens
            MathJax.startup.pageReady = function() {
              return MathJax.startup.defaultPageReady().then(function() {
                console.log('MathJax initial typesetting complete for page ${pageNum}');
              });
            };
          }
          
          // Fallback: Re-typeset after everything loads
          window.addEventListener('load', function() {
            setTimeout(function() {
              if (window.MathJax && MathJax.typesetPromise) {
                console.log('Triggering MathJax typesetting for page ${pageNum}');
                MathJax.typesetPromise()
                  .then(() => console.log('MathJax typesetting complete!'))
                  .catch((err) => console.error('MathJax error:', err));
              } else if (window.MathJax && MathJax.Hub) {
                // Fallback for MathJax v2
                MathJax.Hub.Queue(['Typeset', MathJax.Hub]);
              }
            }, 500);
          });
          
          // Also try after MathJax script loads
          document.addEventListener('DOMContentLoaded', function() {
            var mathJaxScript = document.getElementById('MathJax-script');
            if (mathJaxScript) {
              mathJaxScript.addEventListener('load', function() {
                setTimeout(function() {
                  if (window.MathJax && MathJax.typesetPromise) {
                    MathJax.typesetPromise().catch((err) => console.error('MathJax error:', err));
                  }
                }, 200);
              });
            }
          });
        </script>
      </head>
      <body>
        ${pageElement.outerHTML}
      </body>
      </html>
    `;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (!currentFile?.htmlPath) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-muted-foreground">No HTML file available</p>
      </div>
    );
  }

  return (
    <div className="h-full w-full bg-white dark:bg-gray-900">
      <iframe
        srcDoc={htmlContent}
        className="w-full h-full border-0"
        sandbox="allow-same-origin"
        title="HTML Preview"
      />
    </div>
  );
}
