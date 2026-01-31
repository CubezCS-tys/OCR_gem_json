'use client';

import { JobInfo, cancelJob, retryJob } from '@/lib/pipeline';
import {
    FileText,
    Clock,
    CheckCircle2,
    XCircle,
    Loader2,
    MoreVertical,
    X,
    RotateCcw,
    ExternalLink
} from 'lucide-react';
import { useState } from 'react';

interface JobCardProps {
    job: JobInfo;
    onRefresh?: () => void;
}

const statusConfig: Record<string, { color: string; bgColor: string; icon: React.ComponentType<{ className?: string }> }> = {
    success: { color: 'text-emerald-400', bgColor: 'bg-emerald-500/20', icon: CheckCircle2 },
    failure: { color: 'text-red-400', bgColor: 'bg-red-500/20', icon: XCircle },
    pending: { color: 'text-amber-400', bgColor: 'bg-amber-500/20', icon: Clock },
    started: { color: 'text-blue-400', bgColor: 'bg-blue-500/20', icon: Loader2 },
    processing: { color: 'text-blue-400', bgColor: 'bg-blue-500/20', icon: Loader2 },
    revoked: { color: 'text-slate-400', bgColor: 'bg-slate-500/20', icon: X },
};

export function JobCard({ job, onRefresh }: JobCardProps) {
    const [isLoading, setIsLoading] = useState(false);
    const config = statusConfig[job.status] || statusConfig.pending;
    const StatusIcon = config.icon;

    const pdfName = job.pdf_path?.split('/').pop() || 'Unknown PDF';
    const isActive = job.status === 'started' || job.status === 'processing';

    const handleCancel = async () => {
        setIsLoading(true);
        try {
            await cancelJob(job.task_id, isActive);
            onRefresh?.();
        } catch (e) {
            console.error('Failed to cancel job:', e);
        }
        setIsLoading(false);
    };

    const handleRetry = async () => {
        setIsLoading(true);
        try {
            await retryJob(job.task_id);
            onRefresh?.();
        } catch (e) {
            console.error('Failed to retry job:', e);
        }
        setIsLoading(false);
    };

    return (
        <div className="group relative flex items-center gap-4 p-4 rounded-lg bg-slate-800/30 border border-slate-700/50 hover:bg-slate-800/50 transition-all">
            {/* Status icon */}
            <div className={`p-2 rounded-lg ${config.bgColor}`}>
                <StatusIcon className={`h-5 w-5 ${config.color} ${isActive ? 'animate-spin' : ''}`} />
            </div>

            {/* Job info */}
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <FileText className="h-4 w-4 text-slate-500" />
                    <span className="font-medium text-white truncate">{pdfName}</span>
                </div>
                <div className="flex items-center gap-2 mt-1">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${config.bgColor} ${config.color}`}>
                        {job.status}
                    </span>
                    <span className="text-xs text-slate-500 truncate">
                        {job.task_id.slice(0, 8)}...
                    </span>
                </div>
                {job.error && (
                    <p className="text-xs text-red-400 mt-1 truncate">{job.error}</p>
                )}
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                {job.status === 'failure' && (
                    <button
                        onClick={handleRetry}
                        disabled={isLoading}
                        className="p-2 rounded-lg bg-slate-700/50 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
                        title="Retry"
                    >
                        <RotateCcw className="h-4 w-4" />
                    </button>
                )}
                {(job.status === 'pending' || isActive) && (
                    <button
                        onClick={handleCancel}
                        disabled={isLoading}
                        className="p-2 rounded-lg bg-slate-700/50 hover:bg-red-500/20 text-slate-400 hover:text-red-400 transition-colors"
                        title="Cancel"
                    >
                        <X className="h-4 w-4" />
                    </button>
                )}
                {Boolean(job.result?.output_html) && (
                    <a
                        href={`/viewer?file=${encodeURIComponent(String(job.result?.output_json || ''))}`}
                        className="p-2 rounded-lg bg-slate-700/50 hover:bg-emerald-500/20 text-slate-400 hover:text-emerald-400 transition-colors"
                        title="View Result"
                    >
                        <ExternalLink className="h-4 w-4" />
                    </a>
                )}
            </div>

            {/* Progress bar for active jobs */}
            {isActive && job.progress != null && (
                <div className="absolute bottom-0 left-0 right-0 h-1 bg-slate-700">
                    <div
                        className="h-full bg-blue-500 transition-all duration-300"
                        style={{ width: `${job.progress * 100}%` }}
                    />
                </div>
            )}
        </div>
    );
}

interface JobListProps {
    jobs: JobInfo[];
    isLoading?: boolean;
    onRefresh?: () => void;
    emptyMessage?: string;
}

export function JobList({ jobs, isLoading, onRefresh, emptyMessage = 'No jobs found' }: JobListProps) {
    if (isLoading) {
        return (
            <div className="space-y-3">
                {[1, 2, 3, 4, 5].map((i) => (
                    <div key={i} className="h-20 rounded-lg bg-slate-800/30 animate-pulse" />
                ))}
            </div>
        );
    }

    if (jobs.length === 0) {
        return (
            <div className="text-center py-12 bg-slate-800/30 rounded-xl border border-slate-700/50">
                <FileText className="h-12 w-12 text-slate-600 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-slate-400">{emptyMessage}</h3>
                <p className="text-sm text-slate-500 mt-1">
                    Submit PDFs for processing to see them here
                </p>
            </div>
        );
    }

    return (
        <div className="space-y-3">
            {jobs.map((job) => (
                <JobCard key={job.task_id} job={job} onRefresh={onRefresh} />
            ))}
        </div>
    );
}
