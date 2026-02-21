"use client";

import { useViewerStore } from "@/lib/store";
import { PDFViewer } from "./PDFViewer";
import { HTMLPreview } from "./HTMLPreview";

export function ComparisonView() {
  const { currentFile, documentData } = useViewerStore();

  if (!currentFile || !documentData) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center max-w-md">
          <p className="text-lg text-muted-foreground mb-4">
            No document selected
          </p>
          <p className="text-sm text-muted-foreground">
            Click "Open File" to select a document to view
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 h-full divide-x">
      {/* Left: PDF */}
      <div className="flex flex-col">
        <div className="px-4 py-3 border-b bg-muted/30">
          <h3 className="text-sm font-semibold">Original PDF</h3>
        </div>
        <div className="flex-1 overflow-y-auto bg-slate-50 dark:bg-slate-900">
          <PDFViewer />
        </div>
      </div>

      {/* Right: HTML */}
      <div className="flex flex-col">
        <div className="px-4 py-3 border-b bg-muted/30">
          <h3 className="text-sm font-semibold">Generated HTML</h3>
        </div>
        <div className="flex-1 overflow-hidden">
          <HTMLPreview />
        </div>
      </div>
    </div>
  );
}
