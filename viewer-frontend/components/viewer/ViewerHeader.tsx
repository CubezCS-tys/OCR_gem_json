"use client";

import { useViewerStore } from "@/lib/store";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  FileText,
  Eye,
  Edit3,
  Save,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
  FolderOpen,
} from "lucide-react";
import { toast } from "sonner";
import axios from "axios";
import { useState } from "react";

export function ViewerHeader() {
  const {
    currentFile,
    currentPage,
    totalPages,
    viewMode,
    hasUnsavedChanges,
    documentData,
    setCurrentPage,
    setViewMode,
    resetDocument,
    setLoading,
    setDocumentData,
    setHasUnsavedChanges,
  } = useViewerStore();

  const [isSaving, setIsSaving] = useState(false);

  const handleSave = async () => {
    if (!currentFile || !documentData || !hasUnsavedChanges) return;

    try {
      setIsSaving(true);
      toast.loading("Saving changes and regenerating HTML...");

      // Save updated JSON and regenerate HTML
      const response = await axios.post("/api/save", {
        fileName: currentFile.name,
        documentData,
      });

      toast.dismiss();
      toast.success("Changes saved and HTML regenerated!");
      
      // Update the document with the response (which includes regenerated HTML path)
      setDocumentData(documentData);
      setHasUnsavedChanges(false);
    } catch (err) {
      toast.dismiss();
      const message = err instanceof Error ? err.message : "Failed to save changes";
      toast.error(message);
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = () => {
    if (hasUnsavedChanges) {
      if (confirm("Are you sure you want to discard all changes?")) {
        resetDocument();
        toast.info("Changes discarded");
      }
    }
  };

  return (
    <header className="border-b bg-card">
      <div className="flex items-center justify-between px-6 py-3">
        {/* Left: File Info */}
        <div className="flex items-center gap-4">
          <FileText className="h-5 w-5 text-primary" />
          <div>
            <h1 className="text-lg font-semibold">
              {currentFile ? currentFile.name : "No file selected"}
            </h1>
            {documentData?.metadata && (
              <p className="text-xs text-muted-foreground">
                {documentData.metadata.title || "Untitled Document"}
                {documentData.metadata.language && ` • ${documentData.metadata.language}`}
              </p>
            )}
          </div>
        </div>

        {/* Center: Page Info (no navigation - use sidebar) */}
        {currentFile && totalPages > 0 && (
          <div className="text-center">
            <div className="text-sm font-medium">Page {currentPage} of {totalPages}</div>
            {documentData?.pages[currentPage - 1] && (
              <div className="text-xs text-muted-foreground">
                {documentData.pages[currentPage - 1].text_blocks.length} text blocks
                {documentData.pages[currentPage - 1].tables.length > 0 && 
                  `, ${documentData.pages[currentPage - 1].tables.length} tables`}
              </div>
            )}
          </div>
        )}

        {/* Right: Actions */}
        <div className="flex items-center gap-2">
          {/* Open File Button */}
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              // Trigger the file selector by dispatching a custom event
              window.dispatchEvent(new CustomEvent('openFileSelector'));
            }}
          >
            <FolderOpen className="h-4 w-4 mr-2" />
            Open File
          </Button>

          {/* View Mode Toggle */}
          <div className="flex gap-1 bg-muted p-1 rounded-md">
            <Button
              variant={viewMode === "comparison" ? "default" : "ghost"}
              size="sm"
              onClick={() => setViewMode("comparison")}
            >
              <Eye className="h-4 w-4 mr-2" />
              Compare
            </Button>
            <Button
              variant={viewMode === "editor" ? "default" : "ghost"}
              size="sm"
              onClick={() => setViewMode("editor")}
            >
              <Edit3 className="h-4 w-4 mr-2" />
              Edit
            </Button>
          </div>

          {/* Save/Reset (only in editor mode) */}
          {viewMode === "editor" && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={handleReset}
                disabled={!hasUnsavedChanges || isSaving}
              >
                <RotateCcw className="h-4 w-4 mr-2" />
                Reset
              </Button>
              <Button
                size="sm"
                onClick={handleSave}
                disabled={!hasUnsavedChanges || isSaving}
              >
                <Save className="h-4 w-4 mr-2" />
                {isSaving ? "Saving..." : "Save & Regenerate"}
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Unsaved Changes Warning */}
      {hasUnsavedChanges && (
        <div className="px-6 py-2 bg-yellow-50 dark:bg-yellow-900/20 border-t border-yellow-200 dark:border-yellow-800">
          <p className="text-sm text-yellow-800 dark:text-yellow-200">
            You have unsaved changes. Click "Save & Regenerate" to update the HTML output.
          </p>
        </div>
      )}
    </header>
  );
}
