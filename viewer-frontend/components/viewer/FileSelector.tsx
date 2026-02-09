"use client";

import { useState, useEffect } from "react";
import { useViewerStore } from "@/lib/store";
import { FileInfo } from "@/lib/types";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { FileText, Loader2, FolderOpen } from "lucide-react";
import { Label } from "@/components/ui/label";
import axios from "axios";

export function FileSelector() {
  const {
    isFileSelectorOpen,
    setIsFileSelectorOpen,
    setCurrentFile,
    setCurrentFolder,
    setDocumentData,
    setCurrentPage,
    setLoading,
  } = useViewerStore();

  const [files, setFiles] = useState<FileInfo[]>([]);
  const [loading, setLocalLoading] = useState(true);
  const [selectedFolder, setSelectedFolder] = useState("output_run1");
  const [availableFolders, setAvailableFolders] = useState<string[]>([]);

  useEffect(() => {
    if (isFileSelectorOpen) {
      loadFolders();
      loadFiles(selectedFolder);
    }
  }, [isFileSelectorOpen, selectedFolder]);

  const loadFolders = async () => {
    try {
      const response = await axios.get("/api/folders");
      setAvailableFolders(response.data.folders || ["output_run1"]);
    } catch (err) {
      console.error("Failed to load folders:", err);
      setAvailableFolders(["output_run1"]);
    }
  };

  const loadFiles = async (folder: string) => {
    try {
      setLocalLoading(true);
      const response = await axios.get(`/api/files?folder=${folder}`);
      setFiles(response.data.files || []);
    } catch (err) {
      console.error("Failed to load files:", err);
      setFiles([]);
    } finally {
      setLocalLoading(false);
    }
  };

  const handleSelectFile = async (file: FileInfo) => {
    try {
      setLoading(true);
      setIsFileSelectorOpen(false);

      console.log("📂 FileSelector: Selected file:", file);
      console.log("📁 FileSelector: Selected folder:", selectedFolder);
      console.log("🔗 FileSelector: Has htmlPath?", !!file.htmlPath, file.htmlPath);

      // Store the selected folder
      setCurrentFolder(selectedFolder);

      // Load document data from selected folder
      const response = await axios.get(`/api/document/${file.name}?folder=${selectedFolder}`);
      console.log("📄 FileSelector: Document data loaded");

      setDocumentData(response.data);
      setCurrentFile(file);
      console.log("✅ FileSelector: Set currentFile with htmlPath:", file.htmlPath);

      setCurrentPage(1);
    } catch (err) {
      console.error("❌ FileSelector: Failed to load document:", err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={isFileSelectorOpen} onOpenChange={setIsFileSelectorOpen}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Select a Document</DialogTitle>
          <DialogDescription>
            Choose an output folder and a PDF document to view
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Folder Selector */}
          <div className="space-y-2">
            <Label htmlFor="folder-select" className="flex items-center gap-2">
              <FolderOpen className="h-4 w-4" />
              Output Folder
            </Label>
            <Select value={selectedFolder} onValueChange={setSelectedFolder}>
              <SelectTrigger id="folder-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {availableFolders.map((folder) => (
                  <SelectItem key={folder} value={folder}>
                    {folder}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* File List */}
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : (
            <ScrollArea className="h-96">
              <div className="space-y-2">
                {files.length === 0 ? (
                  <p className="text-center text-muted-foreground py-8">
                    No documents found in {selectedFolder}
                  </p>
                ) : (
                  files.map((file) => (
                    <button
                      key={file.name}
                      onClick={() => handleSelectFile(file)}
                      className="w-full flex items-center gap-3 p-3 border rounded-lg hover:bg-muted/50 transition-colors text-left"
                    >
                      <FileText className="h-5 w-5 text-primary flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="font-medium truncate">{file.name}</p>
                        <div className="flex gap-3 text-xs text-muted-foreground mt-1">
                          {file.pdfPath && <span>PDF</span>}
                          {file.jsonPath && <span>JSON</span>}
                          {file.htmlPath && <span>HTML</span>}
                        </div>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </ScrollArea>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
