"use client";

import { useState, useEffect } from "react";
import { useViewerStore } from "@/lib/store";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { FileText, FolderOpen } from "lucide-react";
import { toast } from "sonner";
import axios from "axios";

export function FileSelector() {
  const {
    availableFiles,
    currentFile,
    setCurrentFile,
    setDocumentData,
    setLoading,
  } = useViewerStore();

  const [isOpen, setIsOpen] = useState(!currentFile);

  // Listen for custom event from header button
  useEffect(() => {
    const handleOpenSelector = () => setIsOpen(true);
    window.addEventListener('openFileSelector', handleOpenSelector);
    return () => window.removeEventListener('openFileSelector', handleOpenSelector);
  }, []);

  const handleFileSelect = async (fileName: string) => {
    const file = availableFiles.find((f) => f.name === fileName);
    if (!file) return;

    try {
      setLoading(true);
      
      // Load JSON data
      const response = await axios.get(`/api/document/${fileName}`);
      
      setCurrentFile(file);
      setDocumentData(response.data);
      setIsOpen(false);
      toast.success(`Loaded ${fileName}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load document";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-card border rounded-lg shadow-lg max-w-md w-full p-6">
        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
          <FileText className="h-5 w-5" />
          Select Document
        </h2>

        {availableFiles.length === 0 ? (
          <div className="text-center py-8">
            <p className="text-muted-foreground mb-4">
              No documents found. Please add PDF and JSON files to the outputs directory.
            </p>
          </div>
        ) : (
          <>
            <p className="text-sm text-muted-foreground mb-4">
              Choose a document to view and edit
            </p>

            <Select onValueChange={handleFileSelect}>
              <SelectTrigger>
                <SelectValue placeholder="Select a file..." />
              </SelectTrigger>
              <SelectContent>
                {availableFiles.map((file) => (
                  <SelectItem key={file.name} value={file.name}>
                    {file.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </>
        )}

        {currentFile && (
          <Button
            variant="ghost"
            className="w-full mt-4"
            onClick={() => setIsOpen(false)}
          >
            Cancel
          </Button>
        )}
      </div>
    </div>
  );
}
