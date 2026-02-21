"use client";

import { useViewerStore } from "@/lib/store";
import { PDFViewer } from "./PDFViewer";
import { TextBlockEditor } from "./TextBlockEditor";
import { TableEditor } from "./TableEditor";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { AlertCircle } from "lucide-react";

export function EditorView() {
  const { documentData, currentPage, currentFile } = useViewerStore();

  if (!documentData) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center max-w-md">
          <p className="text-lg text-muted-foreground mb-4">
            No document selected
          </p>
          <p className="text-sm text-muted-foreground">
            Click "Open File" to select a document to edit
          </p>
        </div>
      </div>
    );
  }

  const page = documentData.pages.find((p) => p.page_number === currentPage);

  if (!page) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-muted-foreground">Page not found</p>
      </div>
    );
  }

  return (
    <div className="flex h-full">
      {/* Left: PDF Viewer */}
      <div className="flex-1 flex flex-col border-r bg-gray-50 dark:bg-gray-950">
        <div className="px-4 py-2 border-b bg-muted/50">
          <h3 className="text-sm font-medium">Original PDF - Page {currentPage}</h3>
        </div>
        <div className="flex-1 overflow-y-auto overflow-x-hidden custom-scrollbar">
          <PDFViewer />
        </div>
      </div>

      <Separator orientation="vertical" className="w-[2px]" />

      {/* Right: Editor Panel */}
      <div className="flex-1 flex flex-col">
        <div className="px-4 py-2 border-b bg-muted/50">
          <h3 className="text-sm font-medium">Edit Content</h3>
        </div>
        <div className="flex-1 overflow-auto custom-scrollbar bg-muted/30">
          <div className="max-w-3xl mx-auto p-6 space-y-6">
            {/* Page Info */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  <span>Page {page.page_number}</span>
                  <div className="flex gap-2">
                    {page.has_multi_column && (
                      <Badge variant="secondary">
                        {page.column_count || 2} Columns
                      </Badge>
                    )}
                    {page.page_direction === "rtl" && (
                      <Badge variant="secondary">RTL</Badge>
                    )}
                  </div>
                </CardTitle>
              </CardHeader>
              {(page.header || page.footer) && (
                <CardContent className="space-y-2">
                  {page.header && (
                    <div className="text-sm">
                      <span className="font-medium">Header:</span>{" "}
                      <span className="text-muted-foreground">{page.header}</span>
                    </div>
                  )}
                  {page.footer && (
                    <div className="text-sm">
                      <span className="font-medium">Footer:</span>{" "}
                      <span className="text-muted-foreground">{page.footer}</span>
                    </div>
                  )}
                </CardContent>
              )}
            </Card>

            {/* Info Banner */}
            <div className="flex items-start gap-3 p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg">
              <AlertCircle className="h-5 w-5 text-blue-600 dark:text-blue-400 mt-0.5" />
              <div className="text-sm text-blue-900 dark:text-blue-100">
                <p className="font-medium mb-1">Text Content Editing Only</p>
                <p className="text-blue-700 dark:text-blue-300">
                  You can edit text content, but layout properties (positions, sizes, styles) are preserved.
                  This ensures the visual structure remains intact while allowing corrections to OCR mistakes.
                </p>
              </div>
            </div>

            {/* Text Blocks */}
            {page.text_blocks.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Text Blocks ({page.text_blocks.length})</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {page.text_blocks.map((block, index) => (
                    <div key={index}>
                      {index > 0 && <Separator className="my-4" />}
                      <TextBlockEditor
                        block={block}
                        pageNumber={page.page_number}
                        blockIndex={index}
                      />
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}

            {/* Tables */}
            {page.tables.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Tables ({page.tables.length})</CardTitle>
                </CardHeader>
                <CardContent className="space-y-6">
                  {page.tables.map((table, index) => (
                    <div key={index}>
                      {index > 0 && <Separator className="my-6" />}
                      <TableEditor
                        table={table}
                        pageNumber={page.page_number}
                        tableIndex={index}
                      />
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}

            {/* Images (Read-only info) */}
            {page.images.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Images ({page.images.length})</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {page.images.map((image, index) => (
                    <div
                      key={index}
                      className="p-3 border rounded-lg bg-muted/50"
                    >
                      <div className="flex items-start justify-between mb-2">
                        <Badge variant="outline">{image.image_type}</Badge>
                        <span className="text-xs text-muted-foreground">
                          Position: {image.bbox_top.toFixed(1)}%, {image.bbox_left.toFixed(1)}%
                        </span>
                      </div>
                      <p className="text-sm">{image.description}</p>
                      {image.caption && (
                        <p className="text-xs text-muted-foreground mt-1">
                          Caption: {image.caption}
                        </p>
                      )}
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
