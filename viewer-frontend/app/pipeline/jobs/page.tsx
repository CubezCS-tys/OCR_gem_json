'use client';

import { useJobs } from '@/lib/hooks/usePipeline';
import { JobList, PipelineNav } from '@/components/pipeline';
import { RefreshCw, Filter } from 'lucide-react';
import { useState } from 'react';

export default function JobsPage() {
    const { jobs, isLoading, refresh } = useJobs(100, 5000);
    const [statusFilter, setStatusFilter] = useState<string>('all');

    const filteredJobs = statusFilter === 'all'
        ? jobs
        : jobs.filter(j => j.status === statusFilter);

    const statusCounts = jobs.reduce((acc, job) => {
        acc[job.status] = (acc[job.status] || 0) + 1;
        return acc;
    }, {} as Record<string, number>);

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-900 to-slate-800">
            <div className="max-w-7xl mx-auto px-6 py-8">
                <PipelineNav />

                {/* Header */}
                <div className="flex items-center justify-between mb-8">
                    <div>
                        <h1 className="text-3xl font-bold text-white">Jobs</h1>
                        <p className="text-slate-400 mt-1">
                            Monitor and manage processing jobs
                        </p>
                    </div>

                    <button
                        onClick={refresh}
                        disabled={isLoading}
                        className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg text-slate-300 transition-colors"
                    >
                        <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
                        <span className="text-sm">Refresh</span>
                    </button>
                </div>

                {/* Filters */}
                <div className="flex items-center gap-2 mb-6 overflow-x-auto pb-2">
                    <Filter className="h-4 w-4 text-slate-500" />
                    <button
                        onClick={() => setStatusFilter('all')}
                        className={`px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${statusFilter === 'all'
                                ? 'bg-slate-700 text-white'
                                : 'text-slate-400 hover:text-white'
                            }`}
                    >
                        All ({jobs.length})
                    </button>
                    {['success', 'failure', 'pending', 'processing', 'started'].map((status) => (
                        <button
                            key={status}
                            onClick={() => setStatusFilter(status)}
                            className={`px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${statusFilter === status
                                    ? 'bg-slate-700 text-white'
                                    : 'text-slate-400 hover:text-white'
                                }`}
                        >
                            {status.charAt(0).toUpperCase() + status.slice(1)} ({statusCounts[status] || 0})
                        </button>
                    ))}
                </div>

                {/* Job List */}
                <JobList
                    jobs={filteredJobs}
                    isLoading={isLoading}
                    onRefresh={refresh}
                />
            </div>
        </div>
    );
}
