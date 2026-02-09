"use client";

import { useState } from "react";
import { useViewerStore } from "@/lib/store";
import { PDFViewer } from "./PDFViewer";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Trash2,
  Plus,
  Save,
  Undo,
  Redo,
  GripVertical,
  Edit3,
  Check,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export function EditorView() {
  const {
    documentData,
    currentPage,
    updateTextBlock,
    updateTableCell,
    addTableRow,
    removeTableRow,
    addTableColumn,
    removeTableColumn,
    undo,
    redo,
    canUndo,
    canRedo,
    saveChanges,
    hasUnsavedChanges,
  } = useViewerStore();

  const [editingBlock, setEditingBlock] = useState<string | null>(null);
  const [editingCell, setEditingCell] = useState<string | null>(null);

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

  const handleSaveBlock = (blockIndex: number, newContent: string) => {
    updateTextBlock(currentPage, blockIndex, newContent);
    setEditingBlock(null);
    toast.success("Text block updated");
  };

  const handleSaveCell = (
    tableIndex: number,
    rowIndex: number,
    cellIndex: number,
    newContent: string
  ) => {
    updateTableCell(currentPage, tableIndex, rowIndex, cellIndex, newContent);
    setEditingCell(null);
    toast.success("Table cell updated");
  };

  const handleSaveDocument = async () => {
    try {
      await saveChanges();
      toast.success("Document saved successfully");
    } catch (error) {
      toast.error("Failed to save document");
    }
  };

  const handleUndo = () => {
    undo();
    toast.info("Undone");
  };

  const handleRedo = () => {
    redo();
    toast.info("Redone");
  };

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
        {/* Editor Toolbar */}
        <div className="px-4 py-3 border-b bg-muted/30 flex items-center justify-between">
          <h3 className="text-sm font-semibold">Page Content Editor</h3>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleUndo}
              disabled={!canUndo()}
              title="Undo (Ctrl+Z)"
            >
              <Undo className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleRedo}
              disabled={!canRedo()}
              title="Redo (Ctrl+Y)"
            >
              <Redo className="h-4 w-4" />
            </Button>
            <div className="w-px h-6 bg-border" />
            <Button
              variant={hasUnsavedChanges ? "default" : "outline"}
              size="sm"
              onClick={handleSaveDocument}
              disabled={!hasUnsavedChanges}
              className="gap-2"
            >
              <Save className="h-4 w-4" />
              {hasUnsavedChanges ? "Save Changes" : "Saved"}
            </Button>
          </div>
        </div>

        <ScrollArea className="flex-1">
          <div className="p-6 space-y-4">
            {/* Page Metadata */}
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
                  <CardTitle className="text-base">
                    Text Blocks ({page.text_blocks.length})
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {page.text_blocks.map((block, idx) => {
                    const blockId = `block-${idx}`;
                    const isEditing = editingBlock === blockId;

                    return (
                      <div
                        key={idx}
                        className="group relative border rounded-lg bg-muted/20 hover:bg-muted/40 transition-colors"
                      >
                        <div className="flex items-start gap-2 p-3">
                          <div className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity cursor-grab">
                            <GripVertical className="h-4 w-4 text-muted-foreground" />
                          </div>
                          <div className="flex-1 space-y-2">
                            <div className="flex items-start justify-between">
                              <Badge variant="outline" className="text-xs">
                                {block.block_type}
                              </Badge>
                              <div className="flex items-center gap-1">
                                {block.is_centered && (
                                  <span className="text-xs text-muted-foreground">
                                    centered
                                  </span>
                                )}
                                {!isEditing && (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => setEditingBlock(blockId)}
                                    className="h-6 px-2 opacity-0 group-hover:opacity-100"
                                  >
                                    <Edit3 className="h-3 w-3" />
                                  </Button>
                                )}
                              </div>
                            </div>

                            {isEditing ? (
                              <div className="space-y-2">
                                <Textarea
                                  defaultValue={block.content}
                                  id={`textarea-${blockId}`}
                                  className="min-h-24 font-mono text-sm"
                                  dir={block.text_direction || "ltr"}
                                />
                                <div className="flex gap-2">
                                  <Button
                                    size="sm"
                                    onClick={() => {
                                      const textarea = document.getElementById(
                                        `textarea-${blockId}`
                                      ) as HTMLTextAreaElement;
                                      handleSaveBlock(idx, textarea.value);
                                    }}
                                    className="gap-2"
                                  >
                                    <Check className="h-3 w-3" />
                                    Save
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => setEditingBlock(null)}
                                    className="gap-2"
                                  >
                                    <X className="h-3 w-3" />
                                    Cancel
                                  </Button>
                                </div>
                              </div>
                            ) : (
                              <div
                                className="text-sm whitespace-pre-wrap"
                                dir={block.text_direction || "ltr"}
                              >
                                {block.content}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </CardContent>
              </Card>
            )}

            {/* Tables */}
            {page.tables && page.tables.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">
                    Tables ({page.tables.length})
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {page.tables.map((table, tableIdx) => (
                    <div key={tableIdx} className="border rounded-lg overflow-hidden">
                      {table.caption && (
                        <div className="px-3 py-2 bg-muted text-sm font-medium flex items-center justify-between">
                          <span>{table.caption}</span>
                        </div>
                      )}

                      {/* Table Controls */}
                      <div className="px-3 py-2 bg-muted/50 border-b flex items-center gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => addTableRow(currentPage, tableIdx)}
                          className="gap-2"
                        >
                          <Plus className="h-3 w-3" />
                          Add Row
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => addTableColumn(currentPage, tableIdx)}
                          className="gap-2"
                        >
                          <Plus className="h-3 w-3" />
                          Add Column
                        </Button>
                      </div>

                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          {table.headers.length > 0 && (
                            <thead>
                              <tr className="bg-muted">
                                {table.headers.map((header, cellIdx) => (
                                  <th
                                    key={cellIdx}
                                    className="border px-3 py-2 text-left font-medium relative group"
                                  >
                                    {header.content}
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      onClick={() =>
                                        removeTableColumn(currentPage, tableIdx, cellIdx)
                                      }
                                      className="absolute top-1 right-1 h-6 w-6 p-0 opacity-0 group-hover:opacity-100"
                                      title="Remove column"
                                    >
                                      <Trash2 className="h-3 w-3" />
                                    </Button>
                                  </th>
                                ))}
                              </tr>
                            </thead>
                          )}
                          <tbody>
                            {table.rows.map((row, rowIdx) => (
                              <tr key={rowIdx} className="group/row">
                                {row.map((cell, cellIdx) => {
                                  const cellId = `cell-${tableIdx}-${rowIdx}-${cellIdx}`;
                                  const isEditingCell = editingCell === cellId;

                                  return (
                                    <td
                                      key={cellIdx}
                                      className="border px-3 py-2 relative group/cell"
                                    >
                                      {isEditingCell ? (
                                        <div className="space-y-1">
                                          <Input
                                            defaultValue={cell.content}
                                            id={`input-${cellId}`}
                                            className="text-sm"
                                          />
                                          <div className="flex gap-1">
                                            <Button
                                              size="sm"
                                              onClick={() => {
                                                const input = document.getElementById(
                                                  `input-${cellId}`
                                                ) as HTMLInputElement;
                                                handleSaveCell(
                                                  tableIdx,
                                                  rowIdx,
                                                  cellIdx,
                                                  input.value
                                                );
                                              }}
                                            >
                                              <Check className="h-3 w-3" />
                                            </Button>
                                            <Button
                                              size="sm"
                                              variant="outline"
                                              onClick={() => setEditingCell(null)}
                                            >
                                              <X className="h-3 w-3" />
                                            </Button>
                                          </div>
                                        </div>
                                      ) : (
                                        <>
                                          {cell.content}
                                          <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => setEditingCell(cellId)}
                                            className="absolute top-1 right-1 h-6 px-2 opacity-0 group-hover/cell:opacity-100"
                                          >
                                            <Edit3 className="h-3 w-3" />
                                          </Button>
                                        </>
                                      )}
                                    </td>
                                  );
                                })}
                                <td className="border-0 px-2">
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() =>
                                      removeTableRow(currentPage, tableIdx, rowIdx)
                                    }
                                    className="h-6 w-6 p-0 opacity-0 group-hover/row:opacity-100"
                                    title="Remove row"
                                  >
                                    <Trash2 className="h-3 w-3 text-destructive" />
                                  </Button>
                                </td>
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
