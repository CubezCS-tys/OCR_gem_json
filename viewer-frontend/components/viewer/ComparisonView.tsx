"use client";

import { useViewerStore } from "@/lib/store";
import { PDFViewer } from "./PDFViewer";
import { HTMLPreview } from "./HTMLPreview";
import { Separator } from "@/components/ui/separator";

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
    <div className="flex h-full">
      {/* Left: PDF Viewer */}
      <div className="flex-1 flex flex-col border-r">
        <div className="px-4 py-2 border-b bg-muted/50">
          <h3 className="text-sm font-medium">Original PDF</h3>
        </div>
        <div className="flex-1 overflow-auto custom-scrollbar">
          <PDFViewer />
        </div>
      </div>

      <Separator orientation="vertical" className="w-[2px]" />

      {/* Right: HTML Preview */}
      <div className="flex-1 flex flex-col">
        <div className="px-4 py-2 border-b bg-muted/50">
          <h3 className="text-sm font-medium">Generated HTML</h3>
        </div>
        <div className="flex-1 overflow-auto custom-scrollbar">
          <HTMLPreview />
        </div>
      </div>
    </div>
  );
}
