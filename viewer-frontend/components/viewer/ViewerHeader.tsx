"use client";

import { useState, useEffect } from "react";
import { useViewerStore } from "@/lib/store";
import { FolderOpen, Eye, Edit, Home, Search as SearchIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useRouter } from "next/navigation";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ExportMenu } from "./ExportMenu";
import { SearchDialog } from "./SearchDialog";

export function ViewerHeader() {
  const router = useRouter();
  const {
    currentFile,
    currentPage,
    documentData,
    setCurrentPage,
    viewMode,
    setViewMode,
    setIsFileSelectorOpen,
  } = useViewerStore();

  const [isSearchOpen, setIsSearchOpen] = useState(false);

  const totalPages = documentData?.pages.length || 0;

  // Ensure page is valid number
  const safeCurrentPage = isNaN(currentPage) || currentPage < 1 ? 1 : currentPage;

  // Global search keyboard shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl/Cmd + F for search
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        e.preventDefault();
        setIsSearchOpen(true);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const handleOpenFileSelector = () => {
    if (typeof setIsFileSelectorOpen === "function") {
      setIsFileSelectorOpen(true);
    } else {
      console.error("setIsFileSelectorOpen is not a function. Store might be corrupted.");
      // Fallback: try to reload the page to reset the store
      window.location.reload();
    }
  };

  return (
    <>
      <header className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-4">
            {/* Home Button */}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.push("/select")}
              className="gap-2"
            >
              <Home className="h-4 w-4" />
              Home
            </Button>
            <div className="h-6 w-px bg-border" />
            <h1 className="text-lg font-semibold">OCR Viewer</h1>
            {currentFile && (
              <span className="text-sm text-muted-foreground">
                {currentFile.name}
              </span>
            )}
          </div>

          <div className="flex items-center gap-4">
            {/* Search Button */}
            {documentData && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setIsSearchOpen(true)}
                className="gap-2"
              >
                <SearchIcon className="h-4 w-4" />
                Search
              </Button>
            )}

            {/* Page Navigation */}
            {documentData && totalPages > 0 && (
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setCurrentPage(Math.max(1, safeCurrentPage - 1))}
                  disabled={safeCurrentPage <= 1}
                >
                  Previous
                </Button>
                <Select
                  value={safeCurrentPage.toString()}
                  onValueChange={(val) => setCurrentPage(parseInt(val, 10))}
                >
                  <SelectTrigger className="w-32">
                    <SelectValue>
                      Page {safeCurrentPage} / {totalPages}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
                      <SelectItem key={page} value={page.toString()}>
                        Page {page}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    setCurrentPage(Math.min(totalPages, safeCurrentPage + 1))
                  }
                  disabled={safeCurrentPage >= totalPages}
                >
                  Next
                </Button>
              </div>
            )}

            {/* View Mode Toggle */}
            <div className="flex items-center gap-1 border rounded-lg p-1">
              <Button
                variant={viewMode === "comparison" ? "default" : "ghost"}
                size="sm"
                onClick={() => setViewMode("comparison")}
                className="gap-2"
              >
                <Eye className="h-4 w-4" />
                Compare
              </Button>
              <Button
                variant={viewMode === "editor" ? "default" : "ghost"}
                size="sm"
                onClick={() => setViewMode("editor")}
                className="gap-2"
              >
                <Edit className="h-4 w-4" />
                Edit
              </Button>
            </div>

            {/* Export Menu */}
            <ExportMenu />

            {/* Open File Button */}
            <Button onClick={handleOpenFileSelector} className="gap-2">
              <FolderOpen className="h-4 w-4" />
              Open File
            </Button>
          </div>
        </div>
      </header>

      {/* Search Dialog */}
      <SearchDialog open={isSearchOpen} onOpenChange={setIsSearchOpen} />
    </>
  );
}
