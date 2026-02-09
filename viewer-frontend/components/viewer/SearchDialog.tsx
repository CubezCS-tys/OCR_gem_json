"use client";

import { useEffect, useState } from "react";
import { useViewerStore } from "@/lib/store";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Search, X, ChevronDown, ChevronUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface SearchDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SearchDialog({ open, onOpenChange }: SearchDialogProps) {
  const {
    searchQuery,
    setSearchQuery,
    searchResults,
    currentSearchIndex,
    performSearch,
    clearSearch,
    goToNextSearchResult,
    goToPreviousSearchResult,
    goToPage,
  } = useViewerStore();

  const [inputValue, setInputValue] = useState(searchQuery);

  useEffect(() => {
    setInputValue(searchQuery);
  }, [searchQuery]);

  // Keyboard shortcuts
  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Enter") {
        if (e.shiftKey) {
          goToPreviousSearchResult();
        } else {
          if (searchResults.length === 0) {
            handleSearch();
          } else {
            goToNextSearchResult();
          }
        }
      } else if (e.key === "Escape") {
        onOpenChange(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, searchResults, goToNextSearchResult, goToPreviousSearchResult, onOpenChange]);

  const handleSearch = () => {
    setSearchQuery(inputValue);
    performSearch();
  };

  const handleClear = () => {
    setInputValue("");
    setSearchQuery("");
    clearSearch();
  };

  const handleSelectResult = (pageNumber: number) => {
    goToPage(pageNumber);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Search Document</DialogTitle>
          <DialogDescription>
            Search across all pages of the document
          </DialogDescription>
        </DialogHeader>

        {/* Search Input */}
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  handleSearch();
                }
              }}
              placeholder="Enter search term..."
              className="pl-10 pr-10"
              autoFocus
            />
            {inputValue && (
              <button
                onClick={handleClear}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
          <Button onClick={handleSearch} disabled={!inputValue.trim()}>
            Search
          </Button>
        </div>

        {/* Search Results Summary */}
        {searchResults.length > 0 && (
          <div className="flex items-center justify-between py-2 border-y">
            <div className="text-sm text-muted-foreground">
              {searchResults.length} result{searchResults.length !== 1 ? "s" : ""} found
              {currentSearchIndex >= 0 && (
                <span className="ml-2 font-medium text-foreground">
                  ({currentSearchIndex + 1} of {searchResults.length})
                </span>
              )}
            </div>
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="sm"
                onClick={goToPreviousSearchResult}
                disabled={searchResults.length === 0}
              >
                <ChevronUp className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={goToNextSearchResult}
                disabled={searchResults.length === 0}
              >
                <ChevronDown className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}

        {/* Search Results List */}
        <ScrollArea className="flex-1 -mx-6 px-6">
          {searchResults.length === 0 && searchQuery && (
            <div className="text-center py-8 text-muted-foreground">
              No results found for "{searchQuery}"
            </div>
          )}

          {searchResults.length === 0 && !searchQuery && (
            <div className="text-center py-8 text-muted-foreground">
              Enter a search term to find content in the document
            </div>
          )}

          <div className="space-y-2 pb-4">
            {searchResults.map((result, idx) => (
              <button
                key={idx}
                onClick={() => handleSelectResult(result.pageNumber)}
                className={`w-full text-left p-3 border rounded-lg transition-colors ${
                  idx === currentSearchIndex
                    ? "border-primary bg-primary/10"
                    : "hover:bg-muted/50"
                }`}
              >
                <div className="flex items-start justify-between mb-2">
                  <Badge variant="secondary" className="text-xs">
                    Page {result.pageNumber}
                  </Badge>
                  {idx === currentSearchIndex && (
                    <Badge variant="default" className="text-xs">
                      Current
                    </Badge>
                  )}
                </div>
                <p className="text-sm text-muted-foreground line-clamp-2">
                  {result.context}
                </p>
              </button>
            ))}
          </div>
        </ScrollArea>

        {/* Keyboard Hints */}
        <div className="text-xs text-muted-foreground border-t pt-3">
          <span className="font-medium">Shortcuts:</span> Enter: Next result | Shift+Enter: Previous result | Esc: Close
        </div>
      </DialogContent>
    </Dialog>
  );
}
