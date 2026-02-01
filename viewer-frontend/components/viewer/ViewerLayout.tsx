"use client";

import { useEffect } from "react";
import { useViewerStore } from "@/lib/store";
import { ViewerHeader } from "./ViewerHeader";
import { ComparisonView } from "./ComparisonView";
import { EditorView } from "./EditorView";
import { FileSelector } from "./FileSelector";
import { PageThumbnails } from "./PageThumbnails";

export function ViewerLayout() {
  const { viewMode, isLoading, documentData } = useViewerStore();

  return (
    <div className="flex flex-col h-screen bg-background">
      <ViewerHeader />

      <div className="flex flex-1 overflow-hidden">
        {/* Page Thumbnails Sidebar */}
        {documentData && (
          <div className="w-56 flex-shrink-0">
            <PageThumbnails />
          </div>
        )}

        {/* Main Content */}
        <div className="flex-1 overflow-hidden">
          {isLoading ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto mb-4"></div>
                <p className="text-muted-foreground">Loading document...</p>
              </div>
            </div>
          ) : viewMode === "comparison" ? (
            <ComparisonView />
          ) : (
            <EditorView />
          )}
        </div>
      </div>

      <FileSelector />
    </div>
  );
}
