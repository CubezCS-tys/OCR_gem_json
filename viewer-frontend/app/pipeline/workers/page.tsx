'use client';

import { useWorkers } from '@/lib/hooks/usePipeline';
import { WorkerList, PipelineNav } from '@/components/pipeline';
import { RefreshCw, Terminal } from 'lucide-react';

export default function WorkersPage() {
    const { workers, isLoading, error } = useWorkers(5000);

    const totalConcurrency = workers.reduce((acc, w) => acc + w.concurrency, 0);
    const totalActive = workers.reduce((acc, w) => acc + w.active_tasks, 0);
    const totalProcessed = workers.reduce((acc, w) => acc + w.processed_total, 0);

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-900 to-slate-800">
            <div className="max-w-7xl mx-auto px-6 py-8">
                <PipelineNav />

                {/* Header */}
                <div className="flex items-center justify-between mb-8">
                    <div>
                        <h1 className="text-3xl font-bold text-white">Workers</h1>
                        <p className="text-slate-400 mt-1">
                            Manage Celery workers and monitor their status
                        </p>
                    </div>
                </div>

                {/* Stats */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
                    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
                        <p className="text-sm text-slate-400">Workers Online</p>
                        <p className="text-2xl font-bold text-white">{workers.length}</p>
                    </div>
                    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
                        <p className="text-sm text-slate-400">Total Concurrency</p>
                        <p className="text-2xl font-bold text-white">{totalConcurrency}</p>
                    </div>
                    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
                        <p className="text-sm text-slate-400">Active Tasks</p>
                        <p className="text-2xl font-bold text-white">{totalActive}</p>
                    </div>
                    <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
                        <p className="text-sm text-slate-400">Total Processed</p>
                        <p className="text-2xl font-bold text-white">{totalProcessed}</p>
                    </div>
                </div>

                {/* Worker List */}
                <div className="mb-8">
                    <h2 className="text-xl font-semibold text-white mb-4">Active Workers</h2>
                    <WorkerList workers={workers} isLoading={isLoading} />
                </div>

                {/* Start worker instructions */}
                <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-6">
                    <div className="flex items-center gap-2 mb-4">
                        <Terminal className="h-5 w-5 text-slate-400" />
                        <h3 className="font-medium text-white">Start a New Worker</h3>
                    </div>

                    <p className="text-sm text-slate-400 mb-4">
                        Run the following command in a terminal to start a new Celery worker:
                    </p>

                    <div className="bg-slate-900/70 rounded-lg p-4 font-mono text-sm overflow-x-auto">
                        <code className="text-emerald-400">
                            cd /home/yassine/OCR_gem_json && source venv/bin/activate && \
                            celery -A celery_config worker --loglevel=info --concurrency=2 --queues=pdf_processing --include=celery_tasks
                        </code>
                    </div>

                    <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                        <div className="bg-slate-900/30 rounded-lg p-3">
                            <p className="text-slate-500 mb-1">Options:</p>
                            <ul className="text-slate-400 space-y-1">
                                <li><code className="text-blue-400">--concurrency=N</code> - Tasks per worker</li>
                                <li><code className="text-blue-400">--hostname=name@%h</code> - Custom name</li>
                                <li><code className="text-blue-400">--loglevel=debug</code> - Verbose logging</li>
                            </ul>
                        </div>
                        <div className="bg-slate-900/30 rounded-lg p-3">
                            <p className="text-slate-500 mb-1">Scaling Tips:</p>
                            <ul className="text-slate-400 space-y-1">
                                <li>• 1 worker per CPU core recommended</li>
                                <li>• Each task uses ~1GB RAM</li>
                                <li>• Concurrency 2-4 per worker is typical</li>
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
