'use client';

import { useState } from 'react';
import { submitJobs, JobSubmission } from '@/lib/pipeline';
import { FilePicker, PipelineNav } from '@/components/pipeline';
import {
    Upload,
    FileText,
    Settings,
    Loader2,
    CheckCircle2,
    X,
    AlertTriangle
} from 'lucide-react';

export default function SubmitPage() {
    const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [result, setResult] = useState<{ success: boolean; message: string; taskIds?: string[] } | null>(null);

    // Options
    const [outputDir, setOutputDir] = useState('/home/yassine/OCR_gem_json/outputs');
    const [outputFormat, setOutputFormat] = useState<'html' | 'json' | 'both' | 'gemini_html'>('both');
    const [resolution, setResolution] = useState<'low' | 'medium' | 'high'>('high');
    const [pagesPerChunk, setPagesPerChunk] = useState(15);
    const [priority, setPriority] = useState<'normal' | 'high' | 'urgent' | 'low'>('normal');

    const handleSubmit = async () => {
        if (selectedFiles.length === 0) return;

        setIsSubmitting(true);
        setResult(null);

        try {
            const submission: JobSubmission = {
                pdf_paths: selectedFiles,
                output_dir: outputDir,
                output_format: outputFormat,
                resolution: resolution,
                pages_per_chunk: pagesPerChunk,
                priority: priority,
            };

            const response = await submitJobs(submission);

            setResult({
                success: true,
                message: `Successfully submitted ${response.total_files} job(s)`,
                taskIds: response.tasks.map(t => t.task_id),
            });

            // Clear selection
            setSelectedFiles([]);
        } catch (error) {
            setResult({
                success: false,
                message: error instanceof Error ? error.message : 'Failed to submit jobs',
            });
        }

        setIsSubmitting(false);
    };

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-900 to-slate-800">
            <div className="max-w-7xl mx-auto px-6 py-8">
                <PipelineNav />

                {/* Header */}
                <div className="mb-8">
                    <h1 className="text-3xl font-bold text-white">Submit Jobs</h1>
                    <p className="text-slate-400 mt-1">
                        Select PDF files and configure processing options
                    </p>
                </div>

                {/* Result message */}
                {result && (
                    <div className={`mb-6 p-4 rounded-lg flex items-start gap-3 ${result.success
                        ? 'bg-emerald-500/10 border border-emerald-500/30'
                        : 'bg-red-500/10 border border-red-500/30'
                        }`}>
                        {result.success ? (
                            <CheckCircle2 className="h-5 w-5 text-emerald-400 mt-0.5" />
                        ) : (
                            <AlertTriangle className="h-5 w-5 text-red-400 mt-0.5" />
                        )}
                        <div>
                            <p className={result.success ? 'text-emerald-400' : 'text-red-400'}>
                                {result.message}
                            </p>
                            {result.taskIds && (
                                <p className="text-sm text-slate-500 mt-1">
                                    Task IDs: {result.taskIds.slice(0, 3).map(id => id.slice(0, 8)).join(', ')}
                                    {result.taskIds.length > 3 && ` +${result.taskIds.length - 3} more`}
                                </p>
                            )}
                        </div>
                        <button
                            onClick={() => setResult(null)}
                            className="ml-auto p-1 hover:bg-slate-700/50 rounded"
                        >
                            <X className="h-4 w-4 text-slate-500" />
                        </button>
                    </div>
                )}

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* File Picker */}
                    <div className="lg:col-span-2">
                        <div className="h-[600px]">
                            <FilePicker
                                selectedFiles={selectedFiles}
                                onSelectFiles={setSelectedFiles}
                                allowMultiple={true}
                            />
                        </div>
                    </div>

                    {/* Options Panel */}
                    <div className="space-y-6">
                        {/* Selected files summary */}
                        <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
                            <div className="flex items-center gap-2 mb-4">
                                <FileText className="h-5 w-5 text-slate-400" />
                                <h3 className="font-medium text-white">Selected Files</h3>
                            </div>

                            {selectedFiles.length === 0 ? (
                                <p className="text-sm text-slate-500">No files selected</p>
                            ) : (
                                <div className="space-y-2 max-h-48 overflow-y-auto">
                                    {selectedFiles.map((file, i) => (
                                        <div
                                            key={file}
                                            className="flex items-center justify-between p-2 bg-slate-700/30 rounded-lg"
                                        >
                                            <span className="text-sm text-slate-300 truncate">
                                                {file.split('/').pop()}
                                            </span>
                                            <button
                                                onClick={() => setSelectedFiles(selectedFiles.filter(f => f !== file))}
                                                className="p-1 hover:bg-slate-600/50 rounded text-slate-500 hover:text-red-400"
                                            >
                                                <X className="h-3 w-3" />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        {/* Processing Options */}
                        <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
                            <div className="flex items-center gap-2 mb-4">
                                <Settings className="h-5 w-5 text-slate-400" />
                                <h3 className="font-medium text-white">Processing Options</h3>
                            </div>

                            <div className="space-y-4">
                                {/* Output Directory */}
                                <div>
                                    <label className="block text-sm text-slate-400 mb-1">Output Directory</label>
                                    <input
                                        type="text"
                                        value={outputDir}
                                        onChange={(e) => setOutputDir(e.target.value)}
                                        className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700/50 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500/50"
                                    />
                                </div>

                                {/* Output Format */}
                                <div>
                                    <label className="block text-sm text-slate-400 mb-1">Output Format</label>
                                    <select
                                        value={outputFormat}
                                        onChange={(e) => setOutputFormat(e.target.value as 'html' | 'json' | 'both' | 'gemini_html')}
                                        className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700/50 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500/50"
                                    >
                                        <option value="both">HTML + JSON</option>
                                        <option value="html">HTML only</option>
                                        <option value="json">JSON only</option>
                                        <option value="gemini_html">Gemini HTML (Direct)</option>
                                    </select>
                                    {outputFormat === 'gemini_html' && (
                                        <p className="text-xs text-amber-400 mt-1">
                                            Uses Gemini&apos;s native HTML output with images injected from PDF
                                        </p>
                                    )}
                                </div>

                                {/* Resolution */}
                                <div>
                                    <label className="block text-sm text-slate-400 mb-1">Resolution</label>
                                    <select
                                        value={resolution}
                                        onChange={(e) => setResolution(e.target.value as 'low' | 'medium' | 'high')}
                                        className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700/50 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500/50"
                                    >
                                        <option value="high">High (Best Quality)</option>
                                        <option value="medium">Medium</option>
                                        <option value="low">Low (Faster)</option>
                                    </select>
                                </div>

                                {/* Pages per Chunk */}
                                <div>
                                    <label className="block text-sm text-slate-400 mb-1">
                                        Pages per Chunk: {pagesPerChunk}
                                    </label>
                                    <input
                                        type="range"
                                        min="5"
                                        max="30"
                                        value={pagesPerChunk}
                                        onChange={(e) => setPagesPerChunk(Number(e.target.value))}
                                        className="w-full accent-blue-500"
                                    />
                                    <div className="flex justify-between text-xs text-slate-500">
                                        <span>5</span>
                                        <span>30</span>
                                    </div>
                                </div>

                                {/* Priority */}
                                <div>
                                    <label className="block text-sm text-slate-400 mb-1">Priority</label>
                                    <select
                                        value={priority}
                                        onChange={(e) => setPriority(e.target.value as 'normal' | 'high' | 'urgent' | 'low')}
                                        className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700/50 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500/50"
                                    >
                                        <option value="urgent">Urgent</option>
                                        <option value="high">High</option>
                                        <option value="normal">Normal</option>
                                        <option value="low">Low</option>
                                    </select>
                                </div>
                            </div>
                        </div>

                        {/* Submit Button */}
                        <button
                            onClick={handleSubmit}
                            disabled={selectedFiles.length === 0 || isSubmitting}
                            className="w-full flex items-center justify-center gap-2 px-6 py-4 bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-500 hover:to-blue-400 disabled:from-slate-700 disabled:to-slate-700 text-white font-medium rounded-xl transition-all shadow-lg shadow-blue-500/25 disabled:shadow-none disabled:cursor-not-allowed"
                        >
                            {isSubmitting ? (
                                <>
                                    <Loader2 className="h-5 w-5 animate-spin" />
                                    Submitting...
                                </>
                            ) : (
                                <>
                                    <Upload className="h-5 w-5" />
                                    Submit {selectedFiles.length} Job{selectedFiles.length !== 1 ? 's' : ''}
                                </>
                            )}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
