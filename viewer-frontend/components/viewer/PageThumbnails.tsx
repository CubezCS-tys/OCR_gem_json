"use client";

import { useViewerStore } from "@/lib/store";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { FileText, Table, Image } from "lucide-react";

export function PageThumbnails() {
  const { documentData, currentPage, setCurrentPage } = useViewerStore();

  if (!documentData) return null;

  return (
    <div className="h-full border-r bg-muted/30">
      <div className="p-3 border-b bg-card">
        <h3 className="text-sm font-semibold">Pages</h3>
        <p className="text-xs text-muted-foreground">
          {documentData.pages.length} pages
        </p>
      </div>
      
      <ScrollArea className="h-[calc(100%-80px)]">
        <div className="p-2 space-y-2">
          {documentData.pages.map((page) => {
            const isActive = page.page_number === currentPage;
            const textBlockCount = page.text_blocks.length;
            const tableCount = page.tables.length;
            const imageCount = page.images.length;

            return (
              <Card
                key={page.page_number}
                className={`p-3 cursor-pointer transition-all hover:shadow-md ${
                  isActive
                    ? "border-primary bg-primary/5 ring-2 ring-primary/20"
                    : "hover:border-primary/50"
                }`}
                onClick={() => setCurrentPage(page.page_number)}
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <div
                      className={`w-8 h-8 rounded flex items-center justify-center text-sm font-bold ${
                        isActive
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {page.page_number}
                    </div>
                  </div>
                  {page.has_multi_column && (
                    <Badge variant="secondary" className="text-xs">
                      {page.column_count || 2} Col
                    </Badge>
                  )}
                </div>

                <div className="space-y-1">
                  {textBlockCount > 0 && (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <FileText className="h-3 w-3" />
                      <span>{textBlockCount} text blocks</span>
                    </div>
                  )}
                  {tableCount > 0 && (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Table className="h-3 w-3" />
                      <span>{tableCount} tables</span>
                    </div>
                  )}
                  {imageCount > 0 && (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Image className="h-3 w-3" />
                      <span>{imageCount} images</span>
                    </div>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      </ScrollArea>
    </div>
  );
}
