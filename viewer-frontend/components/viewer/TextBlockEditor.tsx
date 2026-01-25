"use client";

import { useState } from "react";
import { useViewerStore } from "@/lib/store";
import { TextBlock, TextBlockType } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Edit3, Check, X } from "lucide-react";

interface TextBlockEditorProps {
  block: TextBlock;
  pageNumber: number;
  blockIndex: number;
}

export function TextBlockEditor({ block, pageNumber, blockIndex }: TextBlockEditorProps) {
  const { updateTextBlock } = useViewerStore();
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState(block.content);

  const handleSave = () => {
    updateTextBlock(pageNumber, blockIndex, editedContent);
    setIsEditing(false);
  };

  const handleCancel = () => {
    setEditedContent(block.content);
    setIsEditing(false);
  };

  const getBlockTypeColor = (type: TextBlockType) => {
    const colors = {
      heading: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
      paragraph: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
      list_item: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
      equation: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
      caption: "bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200",
      footnote: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
      quote: "bg-pink-100 text-pink-800 dark:bg-pink-900 dark:text-pink-200",
      code: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200",
    };
    return colors[type] || "";
  };

  return (
    <div className="space-y-2">
      {/* Metadata */}
      <div className="flex items-center gap-2 flex-wrap">
        <Badge className={getBlockTypeColor(block.block_type)}>
          {block.block_type}
          {block.level && ` (Level ${block.level})`}
        </Badge>
        
        {block.list_level && block.list_level > 1 && (
          <Badge variant="outline">Nested Level {block.list_level}</Badge>
        )}
        
        {block.equation_number && (
          <Badge variant="outline">Equation {block.equation_number}</Badge>
        )}
        
        {block.text_direction && block.text_direction !== "auto" && (
          <Badge variant="secondary">{block.text_direction.toUpperCase()}</Badge>
        )}
        
        {block.is_display_math && (
          <Badge variant="secondary">Display Math</Badge>
        )}
      </div>

      {/* Content Editor */}
      {isEditing ? (
        <div className="space-y-2">
          <Textarea
            value={editedContent}
            onChange={(e) => setEditedContent(e.target.value)}
            className="min-h-[100px] text-sm"
            dir={block.text_direction === "rtl" ? "rtl" : "ltr"}
            lang={block.text_direction === "rtl" ? "ar" : "en"}
            style={{ 
              textAlign: block.text_direction === "rtl" ? "right" : "left",
              fontFamily: block.text_direction === "rtl" ? "'Noto Sans Arabic', 'Arial', sans-serif" : "inherit"
            }}
          />
          <div className="flex gap-2">
            <Button size="sm" onClick={handleSave}>
              <Check className="h-4 w-4 mr-1" />
              Save
            </Button>
            <Button size="sm" variant="outline" onClick={handleCancel}>
              <X className="h-4 w-4 mr-1" />
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="group relative">
          <div
            className={`p-3 rounded-lg border bg-muted/30 ${
              block.text_direction === "rtl" ? "text-right" : "text-left"
            }`}
            dir={block.text_direction === "rtl" ? "rtl" : "ltr"}
          >
            {block.block_type === "equation" ? (
              <code className="text-sm font-mono">{block.content}</code>
            ) : (
              <p className="text-sm whitespace-pre-wrap">{block.content}</p>
            )}
          </div>
          <Button
            size="sm"
            variant="outline"
            className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity"
            onClick={() => setIsEditing(true)}
          >
            <Edit3 className="h-3 w-3 mr-1" />
            Edit
          </Button>
        </div>
      )}

      {/* Position Info (Read-only) */}
      {block.bbox_top !== undefined && (
        <div className="text-xs text-muted-foreground">
          Position: Top {block.bbox_top.toFixed(1)}%, Left {block.bbox_left?.toFixed(1)}%
          {block.bbox_width && ` • Size: ${block.bbox_width.toFixed(1)}% × ${block.bbox_height?.toFixed(1)}%`}
        </div>
      )}
    </div>
  );
}
