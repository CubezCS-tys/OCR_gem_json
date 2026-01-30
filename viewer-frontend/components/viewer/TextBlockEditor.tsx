"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useViewerStore } from "@/lib/store";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Edit3, Check, X, CornerDownLeft, Type, Hash } from "lucide-react";

interface TextBlockEditorProps {
  block: any; // Using any to handle varying JSON structures
  pageNumber: number;
  blockIndex: number;
}

type BlockType = 'heading' | 'paragraph' | 'list_item' | 'equation' | 'caption' | 'footnote' | 'quote' | 'code';

export function TextBlockEditor({ block, pageNumber, blockIndex }: TextBlockEditorProps) {
  const { updateTextBlock, setEditingBlockId, editingBlockId } = useViewerStore();
  const [editedContent, setEditedContent] = useState(block.content || '');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Support both 'type' and 'block_type' field names
  const blockType = (block.type || block.block_type || 'paragraph') as BlockType;
  const blockId = block.id || `block-${pageNumber}-${blockIndex}`;

  const isEditing = editingBlockId === blockId;

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
    setEditedContent(block.content || '');
  }, [block.content]);

  const handleEdit = () => {
    setEditingBlockId(blockId);
    setEditedContent(block.content || '');
  };

  const handleSave = () => {
    updateTextBlock(pageNumber - 1, blockIndex, editedContent);
    setEditingBlockId(null);
  };

  const handleCancel = () => {
    setEditedContent(block.content || '');
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

  const getBlockTypeColor = (type: BlockType) => {
    const colors: Record<BlockType, string> = {
      heading: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
      paragraph: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
      list_item: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
      equation: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
      caption: "bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200",
      footnote: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
      quote: "bg-pink-100 text-pink-800 dark:bg-pink-900 dark:text-pink-200",
      code: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200",
    };
    return colors[type] || "bg-gray-100 text-gray-800";
  };

  const getBlockTypeIcon = (type: BlockType) => {
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
        <Badge className={`${getBlockTypeColor(blockType)} flex items-center gap-1`}>
          {getBlockTypeIcon(blockType)}
          {blockType}
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

        {/* Edit button - visible on hover */}
        {!isEditing && (
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto opacity-0 group-hover/block:opacity-100 transition-opacity"
            onClick={handleEdit}
          >
            <Edit3 className="h-4 w-4 mr-1" />
            Edit
          </Button>
        )}
      </div>

      {/* Content */}
      {isEditing ? (
        <div className="space-y-3">
          <Textarea
            ref={textareaRef}
            value={editedContent}
            onChange={(e) => {
              setEditedContent(e.target.value);
              adjustTextareaHeight();
            }}
            onKeyDown={handleKeyDown}
            className="min-h-[100px] resize-none font-mono text-sm leading-relaxed"
            dir={block.text_direction === 'rtl' ? 'rtl' : 'ltr'}
          />

          {/* Stats and Actions */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span>{characterCount} chars</span>
              <span>{wordCount} words</span>
              <span className="flex items-center gap-1">
                <CornerDownLeft className="h-3 w-3" />
                <span className="hidden sm:inline">Ctrl+Enter to save, Esc to cancel</span>
              </span>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleCancel}
              >
                <X className="h-4 w-4 mr-1" />
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={handleSave}
              >
                <Check className="h-4 w-4 mr-1" />
                Save
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <div
          className="p-3 bg-muted/50 rounded-md text-sm leading-relaxed cursor-pointer hover:bg-muted/70 transition-colors"
          dir={block.text_direction === 'rtl' ? 'rtl' : 'ltr'}
          onClick={handleEdit}
        >
          <p className="whitespace-pre-wrap">{block.content || '(empty)'}</p>
        </div>
      )}
    </div>
  );
}
