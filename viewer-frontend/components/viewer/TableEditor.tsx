"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useViewerStore } from "@/lib/store";
import { Table, TableCell } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Edit3, Check, X, Grid3X3 } from "lucide-react";

interface TableEditorProps {
  table: Table;
  pageNumber: number;
  tableIndex: number;
}

// Get cell content as string, handling both string and TableCell types
function getCellContent(cell: string | TableCell): string {
  if (typeof cell === 'string') return cell;
  return cell?.content || '';
}

export function TableEditor({ table, pageNumber, tableIndex }: TableEditorProps) {
  const { updateTableCell } = useViewerStore();
  const [editingCell, setEditingCell] = useState<{ row: number; col: number } | null>(null);
  const [editedValue, setEditedValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const numRows = table.rows?.length || 0;
  const numCols = table.headers?.length || (table.rows?.[0]?.length || 0);

  // Focus input when editing
  useEffect(() => {
    if (editingCell && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editingCell]);

  const startEdit = useCallback((row: number, col: number) => {
    let value: string;
    if (row === -1) {
      // Header row
      value = getCellContent(table.headers[col]);
    } else {
      // Data row
      value = getCellContent(table.rows[row][col]);
    }
    setEditedValue(value);
    setEditingCell({ row, col });
  }, [table]);

  const handleSave = useCallback(() => {
    if (editingCell) {
      updateTableCell(pageNumber - 1, table.id, editingCell.row, editingCell.col, editedValue);
      setEditingCell(null);
    }
  }, [editingCell, pageNumber, table.id, editedValue, updateTableCell]);

  const handleCancel = useCallback(() => {
    setEditingCell(null);
    setEditedValue("");
  }, []);

  // Navigate to next/previous cell
  const navigateCell = useCallback((direction: 'next' | 'prev') => {
    if (!editingCell) return;

    // Save current edit first
    handleSave();

    let { row, col } = editingCell;
    const hasHeaders = table.headers?.length > 0;
    const minRow = hasHeaders ? -1 : 0;
    const maxRow = numRows - 1;
    const maxCol = numCols - 1;

    if (direction === 'next') {
      col++;
      if (col > maxCol) {
        col = 0;
        row++;
        if (row > maxRow) {
          // Wrap to beginning
          row = minRow;
        }
      }
    } else {
      col--;
      if (col < 0) {
        col = maxCol;
        row--;
        if (row < minRow) {
          // Wrap to end
          row = maxRow;
        }
      }
    }

    // Start editing the new cell after a brief delay
    setTimeout(() => startEdit(row, col), 50);
  }, [editingCell, handleSave, startEdit, numRows, numCols, table.headers]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSave();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      handleCancel();
    } else if (e.key === 'Tab') {
      e.preventDefault();
      navigateCell(e.shiftKey ? 'prev' : 'next');
    }
  }, [handleSave, handleCancel, navigateCell]);

  // Detect if content is RTL (Arabic/Hebrew)
  const isRTL = (text: string) => /[\u0600-\u06FF\u0590-\u05FF]/.test(text);

  const renderCell = (content: string | TableCell, row: number, col: number, isHeader: boolean = false) => {
    const cellContent = getCellContent(content);
    const isEditing = editingCell?.row === row && editingCell?.col === col;
    const isRtl = isRTL(cellContent);

    if (isEditing) {
      return (
        <div className="flex items-center gap-1">
          <Input
            ref={inputRef}
            value={editedValue}
            onChange={(e) => setEditedValue(e.target.value)}
            onKeyDown={handleKeyDown}
            className="h-8 text-sm flex-1 min-w-[80px]"
            dir={isRTL(editedValue) ? "rtl" : "ltr"}
            style={{
              textAlign: isRTL(editedValue) ? "right" : "left",
              fontFamily: isRTL(editedValue) ? "'Noto Sans Arabic', 'Arial', sans-serif" : "inherit"
            }}
          />
          <Button size="sm" variant="ghost" onClick={handleSave} className="h-8 w-8 p-0">
            <Check className="h-3 w-3" />
          </Button>
          <Button size="sm" variant="ghost" onClick={handleCancel} className="h-8 w-8 p-0">
            <X className="h-3 w-3" />
          </Button>
        </div>
      );
    }

    return (
      <div
        className="group flex items-center justify-between cursor-pointer min-h-[32px] hover:bg-muted/50 -mx-3 -my-2 px-3 py-2"
        onClick={() => startEdit(row, col)}
        dir={isRtl ? "rtl" : "ltr"}
      >
        <span className={isRtl ? "text-right w-full" : ""}>
          {cellContent || <span className="text-muted-foreground italic text-xs">Empty</span>}
        </span>
        <Button
          size="sm"
          variant="ghost"
          className="opacity-0 group-hover:opacity-100 h-6 w-6 p-0 flex-shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            startEdit(row, col);
          }}
        >
          <Edit3 className="h-3 w-3" />
        </Button>
      </div>
    );
  };

  return (
    <div className="space-y-3 group/table">
      {/* Header with stats */}
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant="outline" className="flex items-center gap-1">
          <Grid3X3 className="h-3 w-3" />
          {numRows} × {numCols}
        </Badge>

        {table.caption && (
          <span className="text-sm font-medium text-muted-foreground">
            {table.caption}
          </span>
        )}
      </div>

      {/* Editing hint */}
      {editingCell && (
        <div className="text-xs text-muted-foreground bg-muted px-2 py-1 rounded">
          Tab to next cell • Shift+Tab for previous • Enter to save • Esc to cancel
        </div>
      )}

      {/* Table */}
      <div className="border rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            {/* Headers */}
            {table.headers?.length > 0 && (
              <thead className="bg-muted">
                <tr>
                  {table.headers.map((header, colIndex) => (
                    <th
                      key={colIndex}
                      className={`px-3 py-2 text-left font-medium border-b border-r last:border-r-0 ${editingCell?.row === -1 && editingCell?.col === colIndex
                          ? 'bg-primary/10'
                          : ''
                        }`}
                    >
                      {renderCell(header, -1, colIndex, true)}
                    </th>
                  ))}
                </tr>
              </thead>
            )}

            {/* Rows */}
            <tbody>
              {table.rows?.map((row, rowIndex) => (
                <tr key={rowIndex} className="border-b last:border-b-0 hover:bg-muted/30">
                  {row.map((cell, colIndex) => (
                    <td
                      key={colIndex}
                      className={`px-3 py-2 border-r last:border-r-0 align-top ${editingCell?.row === rowIndex && editingCell?.col === colIndex
                          ? 'bg-primary/10'
                          : ''
                        }`}
                    >
                      {renderCell(cell, rowIndex, colIndex)}
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
        <div className="text-xs text-muted-foreground opacity-60 group-hover/table:opacity-100 transition-opacity">
          Position: {table.bbox_top.toFixed(1)}% from top, {table.bbox_left?.toFixed(1)}% from left
          {table.bbox_width && ` • Size: ${table.bbox_width.toFixed(1)}% × ${table.bbox_height?.toFixed(1)}%`}
        </div>
      )}
    </div>
  );
}
