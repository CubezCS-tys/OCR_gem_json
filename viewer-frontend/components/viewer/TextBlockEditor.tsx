"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useViewerStore } from "@/lib/store";
import { TextBlock, TextBlockType } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Edit3, Check, X, CornerDownLeft, Type, Hash } from "lucide-react";

interface TextBlockEditorProps {
  block: TextBlock;
  pageNumber: number;
  blockIndex: number;
}

export function TextBlockEditor({ block, pageNumber, blockIndex }: TextBlockEditorProps) {
  const { updateTextBlock, setEditingBlockId, editingBlockId } = useViewerStore();
  const [editedContent, setEditedContent] = useState(block.content);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const isEditing = editingBlockId === block.id;

  // Auto-resize textarea
  const adjustTextareaHeight = useCallback(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.max(100, textarea.scrollHeight)}px`;
    }
  }, []);

  // Focus and adjust height when entering edit mode
  useEffect(() => {
    if (isEditing && textareaRef.current) {
      textareaRef.current.focus();
      adjustTextareaHeight();
      // Place cursor at end
      const len = textareaRef.current.value.length;
      textareaRef.current.setSelectionRange(len, len);
    }
  }, [isEditing, adjustTextareaHeight]);

  // Reset content when block changes
  useEffect(() => {
    setEditedContent(block.content);
  }, [block.content]);

  const handleEdit = () => {
    setEditingBlockId(block.id);
    setEditedContent(block.content);
  };

  const handleSave = () => {
    updateTextBlock(pageNumber - 1, block.id, editedContent);
    setEditingBlockId(null);
  };

  const handleCancel = () => {
    setEditedContent(block.content);
    setEditingBlockId(null);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Ctrl+Enter or Cmd+Enter to save
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleSave();
    }
    // Escape to cancel
    if (e.key === 'Escape') {
      e.preventDefault();
      handleCancel();
    }
  };

  const getBlockTypeColor = (type: TextBlockType) => {
    const colors: Record<TextBlockType, string> = {
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

  const getBlockTypeIcon = (type: TextBlockType) => {
    if (type === 'heading') return <Type className="h-3 w-3" />;
    if (type === 'equation') return <Hash className="h-3 w-3" />;
    return null;
  };

  const characterCount = editedContent.length;
  const wordCount = editedContent.trim().split(/\s+/).filter(Boolean).length;

  return (
    <div className="space-y-2 group/block">
      {/* Metadata Header */}
      <div className="flex items-center gap-2 flex-wrap">
        <Badge className={`${getBlockTypeColor(block.block_type)} flex items-center gap-1`}>
          {getBlockTypeIcon(block.block_type)}
          {block.block_type}
          {block.level && ` (H${block.level})`}
        </Badge>

        {block.list_level && block.list_level > 1 && (
          <Badge variant="outline">Nested Level {block.list_level}</Badge>
        )}

        {block.equation_number && (
          <Badge variant="outline">Eq. {block.equation_number}</Badge>
        )}

        {block.text_direction && block.text_direction !== "auto" && (
          <Badge variant="secondary">{block.text_direction.toUpperCase()}</Badge>
        )}

        {block.is_display_math && (
          <Badge variant="secondary">Display Math</Badge>
        )}

        {block.is_bold && <Badge variant="outline">Bold</Badge>}
        {block.is_italic && <Badge variant="outline">Italic</Badge>}
        {block.is_centered && <Badge variant="outline">Centered</Badge>}
      </div>

      {/* Content Editor */}
      {isEditing ? (
        <div className="space-y-2">
          <div className="relative">
            <Textarea
              ref={textareaRef}
              value={editedContent}
              onChange={(e) => {
                setEditedContent(e.target.value);
                adjustTextareaHeight();
              }}
              onKeyDown={handleKeyDown}
              className="min-h-[100px] text-sm resize-none"
              dir={block.text_direction === "rtl" ? "rtl" : "ltr"}
              lang={block.text_direction === "rtl" ? "ar" : "en"}
              style={{
                textAlign: block.text_direction === "rtl" ? "right" : "left",
                fontFamily: block.text_direction === "rtl"
                  ? "'Noto Sans Arabic', 'Arial', sans-serif"
                  : block.block_type === 'code' || block.block_type === 'equation'
                    ? "'Fira Code', 'Consolas', monospace"
                    : "inherit"
              }}
              placeholder="Enter text content..."
            />

            {/* Character & word count */}
            <div className="absolute bottom-2 right-2 text-xs text-muted-foreground bg-background/80 px-2 py-1 rounded">
              {characterCount} chars • {wordCount} words
            </div>
          </div>

          <div className="flex items-center gap-2 justify-between">
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
            <div className="text-xs text-muted-foreground flex items-center gap-1">
              <CornerDownLeft className="h-3 w-3" />
              Ctrl+Enter to save • Esc to cancel
            </div>
          </div>
        </div>
      ) : (
        <div className="relative">
          <div
            className={`p-3 rounded-lg border bg-muted/30 transition-colors hover:bg-muted/50 ${block.text_direction === "rtl" ? "text-right" : "text-left"
              }`}
            dir={block.text_direction === "rtl" ? "rtl" : "ltr"}
            onClick={handleEdit}
          >
            {block.block_type === "equation" || block.block_type === "code" ? (
              <code className="text-sm font-mono whitespace-pre-wrap">{block.content}</code>
            ) : (
              <p className={`text-sm whitespace-pre-wrap ${block.is_bold ? 'font-bold' : ''} ${block.is_italic ? 'italic' : ''}`}>
                {block.content || <span className="text-muted-foreground italic">Empty block</span>}
              </p>
            )}
          </div>
          <Button
            size="sm"
            variant="outline"
            className="absolute top-2 right-2 opacity-0 group-hover/block:opacity-100 transition-opacity"
            onClick={handleEdit}
          >
            <Edit3 className="h-3 w-3 mr-1" />
            Edit
          </Button>
        </div>
      )}

      {/* Position Info (Read-only) */}
      {block.bbox_top !== undefined && (
        <div className="text-xs text-muted-foreground opacity-60 group-hover/block:opacity-100 transition-opacity">
          Position: {block.bbox_top.toFixed(1)}% from top, {block.bbox_left?.toFixed(1)}% from left
          {block.bbox_width && ` • Size: ${block.bbox_width.toFixed(1)}% × ${block.bbox_height?.toFixed(1)}%`}
        </div>
      )}
    </div>
  );
}
