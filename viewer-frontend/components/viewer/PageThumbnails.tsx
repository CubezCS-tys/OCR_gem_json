"use client";

import { useViewerStore } from "@/lib/store";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { FileText, Table, Image, ArrowRight, ChevronDown, ChevronUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export function PageThumbnails() {
  const { documentData, currentPage, setCurrentPage, totalPages } = useViewerStore();
  const activeCardRef = useRef<HTMLDivElement>(null);
  const [isCollapsed, setIsCollapsed] = useState(false);

  // Scroll active page into view when it changes
  useEffect(() => {
    if (activeCardRef.current) {
      activeCardRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'nearest',
      });
    }
  }, [currentPage]);

  if (!documentData) return null;

  return (
    <div className={`h-full border-r bg-muted/30 flex flex-col transition-all ${isCollapsed ? 'w-16' : 'w-64'}`}>
      {/* Header */}
      <div
        className="p-3 border-b bg-card flex items-center justify-between cursor-pointer"
        onClick={() => setIsCollapsed(!isCollapsed)}
      >
        {!isCollapsed && (
          <div>
            <h3 className="text-sm font-semibold">Pages</h3>
            <p className="text-xs text-muted-foreground">
              {totalPages} pages
            </p>
          </div>
        )}
        {isCollapsed ?
          <ChevronDown className="h-4 w-4 mx-auto" /> :
          <ChevronUp className="h-4 w-4" />
        }
      </div>

      {/* Page List */}
      <ScrollArea className="flex-1">
        <div className={`p-2 space-y-2 ${isCollapsed ? 'items-center' : ''}`}>
          {documentData.pages.map((page) => {
            const isActive = page.page_number === currentPage;
            const textBlockCount = page.text_blocks?.length || 0;
            const tableCount = page.tables?.length || 0;
            const imageCount = page.images?.length || 0;
            const isRTL = page.text_direction === 'rtl';
            const isMultiColumn = page.is_multi_column;

            if (isCollapsed) {
              // Compact view - just page numbers
              return (
                <div
                  key={page.page_number}
                  ref={isActive ? activeCardRef : null}
                  className={`w-10 h-10 mx-auto rounded-md flex items-center justify-center text-sm font-bold cursor-pointer transition-all ${isActive
                      ? "bg-primary text-primary-foreground shadow-md"
                      : "bg-card hover:bg-muted border"
                    }`}
                  onClick={() => setCurrentPage(page.page_number)}
                  title={`Page ${page.page_number}`}
                >
                  {page.page_number}
                </div>
              );
            }

            // Full view
            return (
              <Card
                key={page.page_number}
                ref={isActive ? activeCardRef : null}
                className={`p-3 cursor-pointer transition-all hover:shadow-md ${isActive
                    ? "border-primary bg-primary/5 ring-2 ring-primary/20"
                    : "hover:border-primary/50"
                  }`}
                onClick={() => setCurrentPage(page.page_number)}
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <div
                      className={`w-8 h-8 rounded flex items-center justify-center text-sm font-bold ${isActive
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-muted-foreground"
                        }`}
                    >
                      {page.page_number}
                    </div>
                    {isActive && (
                      <ArrowRight className="h-4 w-4 text-primary" />
                    )}
                  </div>
                  <div className="flex gap-1">
                    {isRTL && (
                      <Badge variant="outline" className="text-xs">
                        RTL
                      </Badge>
                    )}
                    {isMultiColumn && (
                      <Badge variant="secondary" className="text-xs">
                        Multi-col
                      </Badge>
                    )}
                  </div>
                </div>

                {/* Content stats */}
                <div className="grid grid-cols-3 gap-1 text-xs text-muted-foreground">
                  <div className="flex items-center gap-1" title="Text blocks">
                    <FileText className="h-3 w-3" />
                    <span>{textBlockCount}</span>
                  </div>
                  <div className="flex items-center gap-1" title="Tables">
                    <Table className="h-3 w-3" />
                    <span>{tableCount}</span>
                  </div>
                  <div className="flex items-center gap-1" title="Images">
                    <Image className="h-3 w-3" />
                    <span>{imageCount}</span>
                  </div>
                </div>

                {/* Progress indicator for current page */}
                {isActive && (
                  <div className="mt-2 h-1 bg-primary/20 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full transition-all"
                      style={{ width: `${(currentPage / totalPages) * 100}%` }}
                    />
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      </ScrollArea>

      {/* Footer with quick navigation */}
      {!isCollapsed && totalPages > 5 && (
        <div className="p-2 border-t bg-card">
          <div className="flex gap-1 justify-center">
            {/* Quick jump buttons for long documents */}
            <button
              className="px-2 py-1 text-xs bg-muted rounded hover:bg-muted-foreground/20 transition-colors disabled:opacity-50"
              onClick={() => setCurrentPage(1)}
              disabled={currentPage === 1}
            >
              First
            </button>
            <button
              className="px-2 py-1 text-xs bg-muted rounded hover:bg-muted-foreground/20 transition-colors disabled:opacity-50"
              onClick={() => setCurrentPage(Math.ceil(totalPages / 2))}
            >
              Middle
            </button>
            <button
              className="px-2 py-1 text-xs bg-muted rounded hover:bg-muted-foreground/20 transition-colors disabled:opacity-50"
              onClick={() => setCurrentPage(totalPages)}
              disabled={currentPage === totalPages}
            >
              Last
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
