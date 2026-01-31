'use client';

import { usePipeline } from '@/lib/hooks/usePipeline';
import { StatsCards, WorkerList, JobList, PipelineNav } from '@/components/pipeline';
import { RefreshCw, AlertTriangle, CheckCircle2 } from 'lucide-react';

export default function PipelineDashboard() {
    const {
        workers,
        queues,
        jobs,
        stats,
        health,
        isLoading,
        error,
        lastUpdated,
        refresh
    } = usePipeline({ refreshInterval: 5000 });

    const queueDepth = queues.reduce((acc, q) => acc + q.length, 0);

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-900 to-slate-800">
            <div className="max-w-7xl mx-auto px-6 py-8">
                <PipelineNav />

                {/* Header */}
                <div className="flex items-center justify-between mb-8">
                    <div>
                        <h1 className="text-3xl font-bold text-white">Pipeline Dashboard</h1>
                        <p className="text-slate-400 mt-1">
                            Monitor and control your OCR processing pipeline
                        </p>
                    </div>

                    <div className="flex items-center gap-4">
                        {/* Health indicator */}
                        {health && (
                            <div className={`flex items-center gap-2 px-3 py-2 rounded-lg ${health.status === 'healthy'
                                    ? 'bg-emerald-500/10 text-emerald-400'
                                    : health.status === 'degraded'
                                        ? 'bg-amber-500/10 text-amber-400'
                                        : 'bg-red-500/10 text-red-400'
                                }`}>
                                {health.status === 'healthy' ? (
                                    <CheckCircle2 className="h-4 w-4" />
                                ) : (
                                    <AlertTriangle className="h-4 w-4" />
                                )}
                                <span className="text-sm font-medium capitalize">{health.status}</span>
                            </div>
                        )}

                        {/* Refresh button */}
                        <button
                            onClick={refresh}
                            disabled={isLoading}
                            className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg text-slate-300 transition-colors disabled:opacity-50"
                        >
                            <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
                            <span className="text-sm">Refresh</span>
                        </button>
                    </div>
                </div>

                {/* Error banner */}
                {error && (
                    <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-lg flex items-center gap-3">
                        <AlertTriangle className="h-5 w-5 text-red-400" />
                        <p className="text-red-400">{error}</p>
                    </div>
                )}

                {/* Stats Cards */}
                <StatsCards
                    stats={stats}
                    workersOnline={workers.length}
                    queueDepth={queueDepth}
                    isLoading={isLoading}
                />

                {/* Main content grid */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-8">
                    {/* Workers */}
                    <div>
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-xl font-semibold text-white">Workers</h2>
                            <span className="text-sm text-slate-500">
                                {workers.length} online
                            </span>
                        </div>
                        <WorkerList workers={workers} isLoading={isLoading} />
                    </div>

                    {/* Recent Jobs */}
                    <div>
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-xl font-semibold text-white">Recent Jobs</h2>
                            <a
                                href="/pipeline/jobs"
                                className="text-sm text-blue-400 hover:text-blue-300"
                            >
                                View all →
                            </a>
                        </div>
                        <JobList
                            jobs={jobs.slice(0, 5)}
                            isLoading={isLoading}
                            onRefresh={refresh}
                            emptyMessage="No recent jobs"
                        />
                    </div>
                </div>

                {/* Quick actions */}
                <div className="mt-8 p-6 bg-slate-800/50 rounded-xl border border-slate-700/50">
                    <h3 className="text-lg font-semibold text-white mb-4">Quick Actions</h3>
                    <div className="flex flex-wrap gap-4">
                        <a
                            href="/pipeline/submit"
                            className="px-6 py-3 bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-500 hover:to-blue-400 text-white font-medium rounded-lg transition-all shadow-lg shadow-blue-500/25"
                        >
                            Submit New Jobs
                        </a>
                        <a
                            href="/pipeline/workers"
                            className="px-6 py-3 bg-slate-700 hover:bg-slate-600 text-white font-medium rounded-lg transition-colors"
                        >
                            Manage Workers
                        </a>
                        <button
                            onClick={() => window.open('http://localhost:5555', '_blank')}
                            className="px-6 py-3 bg-slate-700 hover:bg-slate-600 text-white font-medium rounded-lg transition-colors"
                        >
                            Open Flower Dashboard
                        </button>
                    </div>
                </div>

                {/* Last updated */}
                {lastUpdated && (
                    <p className="text-center text-sm text-slate-600 mt-8">
                        Last updated: {lastUpdated.toLocaleTimeString()}
                    </p>
                )}
            </div>
        </div>
    );
}
