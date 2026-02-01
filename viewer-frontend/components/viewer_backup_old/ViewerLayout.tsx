"use client";

import { useEffect } from "react";
import { useViewerStore } from "@/lib/store";
import { FileSelector } from "./FileSelector";
import { ViewerHeader } from "./ViewerHeader";
import { ComparisonView } from "./ComparisonView";
import { EditorView } from "./EditorView";
import { PageThumbnails } from "./PageThumbnails";
import { toast } from "sonner";
import axios from "axios";

export function ViewerLayout() {
  const { viewMode, isLoading, error, setError, setAvailableFiles, setLoading, documentData } = useViewerStore();

  useEffect(() => {
    // Load available files on mount
    loadAvailableFiles();
  }, []);

  const loadAvailableFiles = async () => {
    try {
      setLoading(true);
      // Call API to get list of available PDF/JSON files
      const response = await axios.get("/api/files");
      setAvailableFiles(response.data.files);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load files";
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-background">
        <div className="text-center max-w-md p-8">
          <h2 className="text-2xl font-bold text-destructive mb-4">Error</h2>
          <p className="text-muted-foreground mb-6">{error}</p>
          <button
            onClick={() => {
              setError(null);
              loadAvailableFiles();
            }}
            className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-background">
      {/* Header */}
      <ViewerHeader />

      {/* Main Content */}
      <div className="flex-1 overflow-hidden flex">
        {/* Page Thumbnails Sidebar - only show when document is loaded */}
        {documentData && (
          <div className="w-56 flex-shrink-0">
            <PageThumbnails />
          </div>
        )}
        
        {/* Main Viewing Area */}
        <div className="flex-1 overflow-hidden">
          {isLoading ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto mb-4"></div>
                <p className="text-muted-foreground">Loading...</p>
              </div>
            </div>
          ) : viewMode === "comparison" ? (
            <ComparisonView />
          ) : (
            <EditorView />
          )}
        </div>
      </div>

      {/* File Selector Modal */}
      <FileSelector />
    </div>
  );
}
