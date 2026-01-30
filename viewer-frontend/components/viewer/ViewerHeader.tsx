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
import { Input } from "@/components/ui/input";
import {
  FileText,
  Eye,
  Edit3,
  Save,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
  FolderOpen,
  Undo2,
  Redo2,
  Keyboard,
} from "lucide-react";
import { toast } from "sonner";
import axios from "axios";
import { useState, useEffect, useCallback } from "react";

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
    undo,
    redo,
    canUndo,
    canRedo,
  } = useViewerStore();

  const [isSaving, setIsSaving] = useState(false);
  const [pageInputValue, setPageInputValue] = useState(String(currentPage));

  // Sync page input with current page
  useEffect(() => {
    setPageInputValue(String(currentPage));
  }, [currentPage]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Only handle shortcuts when not typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }

      // Ctrl+S - Save
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        if (hasUnsavedChanges && !isSaving) {
          handleSave();
        }
      }

      // Ctrl+Z - Undo
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        if (canUndo()) undo();
      }

      // Ctrl+Shift+Z or Ctrl+Y - Redo
      if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) {
        e.preventDefault();
        if (canRedo()) redo();
      }

      // Arrow keys for page navigation
      if (e.key === 'ArrowLeft' && e.altKey) {
        e.preventDefault();
        handlePrevPage();
      }
      if (e.key === 'ArrowRight' && e.altKey) {
        e.preventDefault();
        handleNextPage();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [hasUnsavedChanges, isSaving, canUndo, canRedo, undo, redo]);

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

  const handlePrevPage = useCallback(() => {
    if (currentPage > 1) {
      setCurrentPage(currentPage - 1);
    }
  }, [currentPage, setCurrentPage]);

  const handleNextPage = useCallback(() => {
    if (currentPage < totalPages) {
      setCurrentPage(currentPage + 1);
    }
  }, [currentPage, totalPages, setCurrentPage]);

  const handlePageInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setPageInputValue(e.target.value);
  };

  const handlePageInputSubmit = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      const page = parseInt(pageInputValue, 10);
      if (!isNaN(page) && page >= 1 && page <= totalPages) {
        setCurrentPage(page);
      } else {
        setPageInputValue(String(currentPage));
        toast.error(`Page must be between 1 and ${totalPages}`);
      }
    }
  };

  const handlePageInputBlur = () => {
    const page = parseInt(pageInputValue, 10);
    if (!isNaN(page) && page >= 1 && page <= totalPages) {
      setCurrentPage(page);
    } else {
      setPageInputValue(String(currentPage));
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

        {/* Center: Page Navigation */}
        {currentFile && totalPages > 0 && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon"
              onClick={handlePrevPage}
              disabled={currentPage <= 1}
              title="Previous page (Alt+←)"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>

            <div className="flex items-center gap-1">
              <Input
                type="text"
                value={pageInputValue}
                onChange={handlePageInputChange}
                onKeyDown={handlePageInputSubmit}
                onBlur={handlePageInputBlur}
                className="w-14 h-8 text-center"
                title="Enter page number"
              />
              <span className="text-sm text-muted-foreground">of {totalPages}</span>
            </div>

            <Button
              variant="outline"
              size="icon"
              onClick={handleNextPage}
              disabled={currentPage >= totalPages}
              title="Next page (Alt+→)"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>

            {/* Page info */}
            {documentData?.pages?.[currentPage - 1] && (
              <div className="text-xs text-muted-foreground ml-2 hidden lg:block">
                {documentData.pages[currentPage - 1]?.text_blocks?.length || 0} blocks
                {(documentData.pages[currentPage - 1]?.tables?.length || 0) > 0 &&
                  `, ${documentData.pages[currentPage - 1]?.tables?.length} tables`}
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
            <span className="hidden sm:inline">Open File</span>
          </Button>

          {/* View Mode Toggle */}
          <div className="flex gap-1 bg-muted p-1 rounded-md">
            <Button
              variant={viewMode === "comparison" ? "default" : "ghost"}
              size="sm"
              onClick={() => setViewMode("comparison")}
            >
              <Eye className="h-4 w-4 mr-2" />
              <span className="hidden sm:inline">Compare</span>
            </Button>
            <Button
              variant={viewMode === "editor" ? "default" : "ghost"}
              size="sm"
              onClick={() => setViewMode("editor")}
            >
              <Edit3 className="h-4 w-4 mr-2" />
              <span className="hidden sm:inline">Edit</span>
            </Button>
          </div>

          {/* Undo/Redo (only in editor mode) */}
          {viewMode === "editor" && (
            <div className="flex gap-1">
              <Button
                variant="ghost"
                size="icon"
                onClick={undo}
                disabled={!canUndo()}
                title="Undo (Ctrl+Z)"
              >
                <Undo2 className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={redo}
                disabled={!canRedo()}
                title="Redo (Ctrl+Y)"
              >
                <Redo2 className="h-4 w-4" />
              </Button>
            </div>
          )}

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
                <span className="hidden sm:inline">Reset</span>
              </Button>
              <Button
                size="sm"
                onClick={handleSave}
                disabled={!hasUnsavedChanges || isSaving}
                title="Save (Ctrl+S)"
              >
                <Save className="h-4 w-4 mr-2" />
                {isSaving ? "Saving..." : "Save"}
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Unsaved Changes Warning */}
      {hasUnsavedChanges && (
        <div className="px-6 py-2 bg-yellow-50 dark:bg-yellow-900/20 border-t border-yellow-200 dark:border-yellow-800 flex items-center justify-between">
          <p className="text-sm text-yellow-800 dark:text-yellow-200">
            You have unsaved changes
          </p>
          <div className="flex items-center gap-2 text-xs text-yellow-600 dark:text-yellow-400">
            <Keyboard className="h-3 w-3" />
            <span className="hidden sm:inline">Ctrl+S to save • Ctrl+Z to undo</span>
          </div>
        </div>
      )}
    </header>
  );
}
