"use client";

import { useState } from "react";
import { useViewerStore } from "@/lib/store";
import { Table } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Edit3, Check, X } from "lucide-react";

interface TableEditorProps {
  table: Table;
  pageNumber: number;
  tableIndex: number;
}

export function TableEditor({ table, pageNumber, tableIndex }: TableEditorProps) {
  const { updateTableCell } = useViewerStore();
  const [editingCell, setEditingCell] = useState<{ row: number; col: number } | null>(null);
  const [editedValue, setEditedValue] = useState("");

  const startEdit = (row: number, col: number) => {
    const value = row === -1 ? table.headers[col] : table.rows[row][col];
    setEditedValue(value);
    setEditingCell({ row, col });
  };

  const handleSave = () => {
    if (editingCell) {
      updateTableCell(pageNumber, tableIndex, editingCell.row, editingCell.col, editedValue);
      setEditingCell(null);
    }
  };

  const handleCancel = () => {
    setEditingCell(null);
    setEditedValue("");
  };

  return (
    <div className="space-y-3">
      {/* Caption */}
      {table.caption && (
        <div className="text-sm font-medium text-muted-foreground">
          {table.caption}
        </div>
      )}

      {/* Table */}
      <div className="border rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            {/* Headers */}
            {table.headers.length > 0 && (
              <thead className="bg-muted">
                <tr>
                  {table.headers.map((header, colIndex) => (
                    <th
                      key={colIndex}
                      className="px-3 py-2 text-left font-medium border-b border-r last:border-r-0"
                    >
                      {editingCell?.row === -1 && editingCell?.col === colIndex ? (
                        <div className="flex items-center gap-2">
                          <Input
                            value={editedValue}
                            onChange={(e) => setEditedValue(e.target.value)}
                            className="h-8 text-sm"
                            autoFocus
                            dir={/[\u0600-\u06FF]/.test(editedValue) ? "rtl" : "ltr"}
                            lang={/[\u0600-\u06FF]/.test(editedValue) ? "ar" : "en"}
                            style={{
                              textAlign: /[\u0600-\u06FF]/.test(editedValue) ? "right" : "left",
                              fontFamily: /[\u0600-\u06FF]/.test(editedValue) ? "'Noto Sans Arabic', 'Arial', sans-serif" : "inherit"
                            }}
                          />
                          <Button size="sm" variant="ghost" onClick={handleSave}>
                            <Check className="h-3 w-3" />
                          </Button>
                          <Button size="sm" variant="ghost" onClick={handleCancel}>
                            <X className="h-3 w-3" />
                          </Button>
                        </div>
                      ) : (
                        <div className="group flex items-center justify-between">
                          <span>{header}</span>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="opacity-0 group-hover:opacity-100 h-6 w-6 p-0"
                            onClick={() => startEdit(-1, colIndex)}
                          >
                            <Edit3 className="h-3 w-3" />
                          </Button>
                        </div>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
            )}

            {/* Rows */}
            <tbody>
              {table.rows.map((row, rowIndex) => (
                <tr key={rowIndex} className="border-b last:border-b-0">
                  {row.map((cell, colIndex) => (
                    <td
                      key={colIndex}
                      className="px-3 py-2 border-r last:border-r-0 align-top"
                    >
                      {editingCell?.row === rowIndex &&
                      editingCell?.col === colIndex ? (
                        <div className="flex items-center gap-2">
                          <Input
                            value={editedValue}
                            onChange={(e) => setEditedValue(e.target.value)}
                            className="h-8 text-sm"
                            autoFocus
                            dir={/[\u0600-\u06FF]/.test(editedValue) ? "rtl" : "ltr"}
                            lang={/[\u0600-\u06FF]/.test(editedValue) ? "ar" : "en"}
                            style={{
                              textAlign: /[\u0600-\u06FF]/.test(editedValue) ? "right" : "left",
                              fontFamily: /[\u0600-\u06FF]/.test(editedValue) ? "'Noto Sans Arabic', 'Arial', sans-serif" : "inherit"
                            }}
                          />
                          <Button size="sm" variant="ghost" onClick={handleSave}>
                            <Check className="h-3 w-3" />
                          </Button>
                          <Button size="sm" variant="ghost" onClick={handleCancel}>
                            <X className="h-3 w-3" />
                          </Button>
                        </div>
                      ) : (
                        <div className="group flex items-center justify-between">
                          <span>{cell}</span>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="opacity-0 group-hover:opacity-100 h-6 w-6 p-0"
                            onClick={() => startEdit(rowIndex, colIndex)}
                          >
                            <Edit3 className="h-3 w-3" />
                          </Button>
                        </div>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Position Info (Read-only) */}
      {table.bbox_top !== undefined && (
        <div className="text-xs text-muted-foreground">
          Position: Top {table.bbox_top.toFixed(1)}%, Left {table.bbox_left?.toFixed(1)}%
          {table.bbox_width && ` • Size: ${table.bbox_width.toFixed(1)}% × ${table.bbox_height?.toFixed(1)}%`}
        </div>
      )}
    </div>
  );
}
