"use client";

import { useViewerStore } from "@/lib/store";
import { PDFViewer } from "./PDFViewer";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";

export function EditorView() {
  const { documentData, currentPage } = useViewerStore();

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
    <div className="grid grid-cols-2 h-full divide-x">
      {/* Left: PDF */}
      <div className="flex flex-col">
        <div className="px-4 py-3 border-b bg-muted/30">
          <h3 className="text-sm font-semibold">Original PDF - Page {currentPage}</h3>
        </div>
        <div className="flex-1 overflow-y-auto bg-slate-50 dark:bg-slate-900">
          <PDFViewer />
        </div>
      </div>

      {/* Right: Content Editor */}
      <div className="flex flex-col">
        <div className="px-4 py-3 border-b bg-muted/30">
          <h3 className="text-sm font-semibold">Page Content</h3>
        </div>
        <ScrollArea className="flex-1">
          <div className="p-6 space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between text-base">
                  <span>Page {page.page_number}</span>
                  <div className="flex gap-2">
                    {page.has_multi_column && (
                      <Badge variant="secondary" className="text-xs">
                        {page.column_count || 2} Columns
                      </Badge>
                    )}
                    {page.page_direction === "rtl" && (
                      <Badge variant="secondary" className="text-xs">RTL</Badge>
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

            {/* Text Blocks */}
            {page.text_blocks && page.text_blocks.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Text Blocks ({page.text_blocks.length})</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {page.text_blocks.map((block, idx) => (
                    <div key={idx} className="p-3 border rounded-lg bg-muted/20">
                      <div className="flex items-start justify-between mb-2">
                        <Badge variant="outline" className="text-xs">{block.block_type}</Badge>
                        {block.is_centered && (
                          <span className="text-xs text-muted-foreground">centered</span>
                        )}
                      </div>
                      <div
                        className="text-sm whitespace-pre-wrap"
                        dir={block.text_direction || 'ltr'}
                      >
                        {block.content}
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}

            {/* Tables */}
            {page.tables && page.tables.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Tables ({page.tables.length})</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {page.tables.map((table, idx) => (
                    <div key={idx} className="border rounded-lg overflow-hidden">
                      {table.caption && (
                        <div className="px-3 py-2 bg-muted text-sm font-medium">
                          {table.caption}
                        </div>
                      )}
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          {table.headers.length > 0 && (
                            <thead>
                              <tr className="bg-muted">
                                {table.headers.map((header, cellIdx) => (
                                  <th
                                    key={cellIdx}
                                    className="border px-3 py-2 text-left font-medium"
                                  >
                                    {header.content}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                          )}
                          <tbody>
                            {table.rows.map((row, rowIdx) => (
                              <tr key={rowIdx}>
                                {row.map((cell, cellIdx) => (
                                  <td
                                    key={cellIdx}
                                    className="border px-3 py-2"
                                  >
                                    {cell.content}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}
