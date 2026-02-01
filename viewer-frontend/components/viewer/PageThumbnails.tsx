"use client";

import { useViewerStore } from "@/lib/store";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

export function PageThumbnails() {
  const { documentData, currentPage, setCurrentPage } = useViewerStore();

  if (!documentData) return null;

  return (
    <div className="h-full border-r bg-muted/20">
      <div className="px-3 py-3 border-b bg-background/95">
        <h3 className="text-sm font-semibold">Pages</h3>
        <p className="text-xs text-muted-foreground mt-1">
          {documentData.pages.length} total
        </p>
      </div>
      <ScrollArea className="h-[calc(100%-4rem)]">
        <div className="p-2 space-y-2">
          {documentData.pages.map((page) => {
            const isActive = page.page_number === currentPage;
            return (
              <button
                key={page.page_number}
                onClick={() => setCurrentPage(page.page_number)}
                className={cn(
                  "w-full p-3 rounded-lg border-2 transition-all text-left",
                  isActive
                    ? "border-primary bg-primary/10 shadow-sm"
                    : "border-transparent bg-background hover:border-muted-foreground/30 hover:bg-muted/50"
                )}
              >
                <div className="flex items-center justify-between">
                  <span className={cn(
                    "text-sm font-medium",
                    isActive ? "text-primary" : "text-foreground"
                  )}>
                    Page {page.page_number}
                  </span>
                  {isActive && (
                    <div className="h-2 w-2 rounded-full bg-primary animate-pulse" />
                  )}
                </div>
                <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                  {page.text_blocks && (
                    <div className="flex items-center gap-1">
                      <span className="font-medium">{page.text_blocks.length}</span>
                      <span>text blocks</span>
                    </div>
                  )}
                  {page.tables && page.tables.length > 0 && (
                    <div className="flex items-center gap-1">
                      <span className="font-medium">{page.tables.length}</span>
                      <span>tables</span>
                    </div>
                  )}
                  {page.images && page.images.length > 0 && (
                    <div className="flex items-center gap-1">
                      <span className="font-medium">{page.images.length}</span>
                      <span>images</span>
                    </div>
                  )}
                  {page.has_multi_column && (
                    <div className="text-primary/70 font-medium">
                      {page.column_count || 2} columns
                    </div>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </ScrollArea>
    </div>
  );
}
