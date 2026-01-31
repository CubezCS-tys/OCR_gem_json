'use client';

import { useState, useEffect } from 'react';
import { FileInfo, listFiles, getConfiguredDirectories } from '@/lib/pipeline';
import {
    Folder,
    FileText,
    ChevronRight,
    ChevronDown,
    Check,
    ArrowLeft,
    RefreshCw,
    Search
} from 'lucide-react';

interface FilePickerProps {
    selectedFiles: string[];
    onSelectFiles: (files: string[]) => void;
    allowMultiple?: boolean;
}

export function FilePicker({ selectedFiles, onSelectFiles, allowMultiple = true }: FilePickerProps) {
    const [currentPath, setCurrentPath] = useState<string | null>(null);
    const [files, setFiles] = useState<FileInfo[]>([]);
    const [directories, setDirectories] = useState<Array<{ path: string; exists: boolean; absolute: string }>>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [pathHistory, setPathHistory] = useState<string[]>([]);

    // Load configured directories on mount
    useEffect(() => {
        getConfiguredDirectories()
            .then(setDirectories)
            .catch(() => setDirectories([]));
    }, []);

    // Load files when path changes
    useEffect(() => {
        setIsLoading(true);
        listFiles(currentPath || undefined)
            .then(setFiles)
            .catch(() => setFiles([]))
            .finally(() => setIsLoading(false));
    }, [currentPath]);

    const handleNavigate = (path: string) => {
        if (currentPath) {
            setPathHistory(prev => [...prev, currentPath]);
        }
        setCurrentPath(path);
    };

    const handleBack = () => {
        if (pathHistory.length > 0) {
            const prev = pathHistory[pathHistory.length - 1];
            setPathHistory(pathHistory.slice(0, -1));
            setCurrentPath(prev);
        } else {
            setCurrentPath(null);
        }
    };

    const handleSelectFile = (file: FileInfo) => {
        if (file.is_directory) {
            handleNavigate(file.path);
            return;
        }

        if (allowMultiple) {
            if (selectedFiles.includes(file.path)) {
                onSelectFiles(selectedFiles.filter(f => f !== file.path));
            } else {
                onSelectFiles([...selectedFiles, file.path]);
            }
        } else {
            onSelectFiles([file.path]);
        }
    };

    const handleSelectAll = () => {
        const pdfFiles = files.filter(f => !f.is_directory).map(f => f.path);
        const allSelected = pdfFiles.every(f => selectedFiles.includes(f));

        if (allSelected) {
            onSelectFiles(selectedFiles.filter(f => !pdfFiles.includes(f)));
        } else {
            // Combine and deduplicate
            const combined = [...selectedFiles, ...pdfFiles];
            const unique = combined.filter((v, i, a) => a.indexOf(v) === i);
            onSelectFiles(unique);
        }
    };

    const filteredFiles = files.filter(file =>
        file.name.toLowerCase().includes(searchQuery.toLowerCase())
    );

    const pdfCount = files.filter(f => !f.is_directory).length;
    const selectedInDir = files.filter(f => !f.is_directory && selectedFiles.includes(f.path)).length;

    return (
        <div className="flex flex-col h-full bg-slate-800/50 rounded-xl border border-slate-700/50 overflow-hidden">
            {/* Header */}
            <div className="flex items-center gap-2 p-3 border-b border-slate-700/50 bg-slate-800/80">
                <button
                    onClick={handleBack}
                    disabled={!currentPath && pathHistory.length === 0}
                    className="p-2 rounded-lg hover:bg-slate-700/50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                    <ArrowLeft className="h-4 w-4 text-slate-400" />
                </button>

                <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-400 truncate">
                        {currentPath || 'Select a directory'}
                    </p>
                </div>

                <button
                    onClick={() => listFiles(currentPath || undefined).then(setFiles)}
                    className="p-2 rounded-lg hover:bg-slate-700/50 transition-colors"
                >
                    <RefreshCw className="h-4 w-4 text-slate-400" />
                </button>
            </div>

            {/* Search */}
            <div className="p-3 border-b border-slate-700/50">
                <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
                    <input
                        type="text"
                        placeholder="Search files..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="w-full pl-10 pr-4 py-2 bg-slate-900/50 border border-slate-700/50 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50"
                    />
                </div>
            </div>

            {/* Directory list or file list */}
            <div className="flex-1 overflow-y-auto">
                {!currentPath && directories.length > 0 ? (
                    <div className="p-3">
                        <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Configured Directories</p>
                        <div className="space-y-2">
                            {directories.map((dir, i) => (
                                <button
                                    key={i}
                                    onClick={() => dir.exists && handleNavigate(dir.absolute)}
                                    disabled={!dir.exists}
                                    className="w-full flex items-center gap-3 p-3 rounded-lg bg-slate-700/30 hover:bg-slate-700/50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-left"
                                >
                                    <Folder className="h-5 w-5 text-amber-400" />
                                    <div className="flex-1 min-w-0">
                                        <p className="text-sm text-white truncate">{dir.path}</p>
                                        {!dir.exists && (
                                            <p className="text-xs text-red-400">Directory not found</p>
                                        )}
                                    </div>
                                    <ChevronRight className="h-4 w-4 text-slate-500" />
                                </button>
                            ))}
                        </div>
                    </div>
                ) : isLoading ? (
                    <div className="p-8 text-center">
                        <div className="animate-spin h-8 w-8 border-2 border-slate-600 border-t-blue-500 rounded-full mx-auto" />
                        <p className="text-sm text-slate-500 mt-4">Loading files...</p>
                    </div>
                ) : filteredFiles.length === 0 ? (
                    <div className="p-8 text-center">
                        <FileText className="h-12 w-12 text-slate-600 mx-auto mb-4" />
                        <p className="text-sm text-slate-500">No PDF files found</p>
                    </div>
                ) : (
                    <div className="p-2">
                        {/* Select all */}
                        {pdfCount > 0 && allowMultiple && (
                            <button
                                onClick={handleSelectAll}
                                className="w-full flex items-center gap-3 p-2 mb-2 rounded-lg bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 transition-colors"
                            >
                                <div className={`w-5 h-5 rounded border-2 flex items-center justify-center ${selectedInDir === pdfCount && pdfCount > 0
                                    ? 'bg-blue-500 border-blue-500'
                                    : 'border-slate-500'
                                    }`}>
                                    {selectedInDir === pdfCount && pdfCount > 0 && (
                                        <Check className="h-3 w-3 text-white" />
                                    )}
                                </div>
                                <span className="text-sm">
                                    Select all ({pdfCount} files)
                                </span>
                            </button>
                        )}

                        {/* File list */}
                        <div className="space-y-1">
                            {filteredFiles.map((file) => {
                                const isSelected = selectedFiles.includes(file.path);

                                return (
                                    <button
                                        key={file.path}
                                        onClick={() => handleSelectFile(file)}
                                        className={`w-full flex items-center gap-3 p-2 rounded-lg transition-colors text-left ${isSelected
                                            ? 'bg-emerald-500/20 border border-emerald-500/30'
                                            : 'hover:bg-slate-700/50'
                                            }`}
                                    >
                                        {file.is_directory ? (
                                            <Folder className="h-5 w-5 text-amber-400" />
                                        ) : (
                                            <div className={`w-5 h-5 rounded border-2 flex items-center justify-center ${isSelected
                                                ? 'bg-emerald-500 border-emerald-500'
                                                : 'border-slate-500'
                                                }`}>
                                                {isSelected && <Check className="h-3 w-3 text-white" />}
                                            </div>
                                        )}

                                        <div className="flex-1 min-w-0">
                                            <p className="text-sm text-white truncate">{file.name}</p>
                                            {!file.is_directory && file.size && (
                                                <p className="text-xs text-slate-500">
                                                    {(file.size / 1024 / 1024).toFixed(2)} MB
                                                </p>
                                            )}
                                        </div>

                                        {file.is_directory && (
                                            <ChevronRight className="h-4 w-4 text-slate-500" />
                                        )}
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                )}
            </div>

            {/* Footer with selection count */}
            {selectedFiles.length > 0 && (
                <div className="p-3 border-t border-slate-700/50 bg-slate-800/80">
                    <p className="text-sm text-slate-400">
                        <span className="text-emerald-400 font-medium">{selectedFiles.length}</span> file{selectedFiles.length !== 1 ? 's' : ''} selected
                    </p>
                </div>
            )}
        </div>
    );
}
