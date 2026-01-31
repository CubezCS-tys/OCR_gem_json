'use client';

import { WorkerInfo } from '@/lib/pipeline';
import { Server, Cpu, Activity, MoreVertical } from 'lucide-react';

interface WorkerCardProps {
    worker: WorkerInfo;
    onAction?: (action: 'shutdown' | 'pool_restart') => void;
}

export function WorkerCard({ worker, onAction }: WorkerCardProps) {
    const isActive = worker.active_tasks > 0;

    return (
        <div className="relative overflow-hidden rounded-xl bg-slate-800/50 backdrop-blur-sm border border-slate-700/50 p-4 transition-all hover:bg-slate-800/70">
            {/* Status indicator */}
            <div className="absolute top-4 right-4">
                <div className={`flex items-center gap-2 px-2 py-1 rounded-full text-xs font-medium ${isActive
                        ? 'bg-emerald-500/20 text-emerald-400'
                        : 'bg-blue-500/20 text-blue-400'
                    }`}>
                    <span className={`w-2 h-2 rounded-full ${isActive ? 'bg-emerald-400 animate-pulse' : 'bg-blue-400'
                        }`} />
                    {isActive ? 'Processing' : 'Idle'}
                </div>
            </div>

            {/* Worker info */}
            <div className="flex items-start gap-3">
                <div className="p-2 rounded-lg bg-slate-700/50">
                    <Server className="h-5 w-5 text-slate-400" />
                </div>
                <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-white truncate pr-20">
                        {worker.hostname.split('@')[0]}
                    </h3>
                    <p className="text-sm text-slate-400 truncate">
                        {worker.hostname}
                    </p>
                </div>
            </div>

            {/* Stats */}
            <div className="mt-4 grid grid-cols-3 gap-4">
                <div>
                    <p className="text-xs text-slate-500">Active</p>
                    <p className="text-lg font-semibold text-white">{worker.active_tasks}</p>
                </div>
                <div>
                    <p className="text-xs text-slate-500">Processed</p>
                    <p className="text-lg font-semibold text-white">{worker.processed_total}</p>
                </div>
                <div>
                    <p className="text-xs text-slate-500">Concurrency</p>
                    <p className="text-lg font-semibold text-white">{worker.concurrency}</p>
                </div>
            </div>

            {/* Concurrency bar */}
            <div className="mt-4">
                <div className="flex justify-between text-xs text-slate-500 mb-1">
                    <span>Capacity</span>
                    <span>{worker.active_tasks}/{worker.concurrency}</span>
                </div>
                <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                    <div
                        className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400 transition-all duration-300"
                        style={{ width: `${(worker.active_tasks / worker.concurrency) * 100}%` }}
                    />
                </div>
            </div>
        </div>
    );
}

interface WorkerListProps {
    workers: WorkerInfo[];
    isLoading?: boolean;
}

export function WorkerList({ workers, isLoading }: WorkerListProps) {
    if (isLoading) {
        return (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {[1, 2, 3].map((i) => (
                    <div key={i} className="h-48 rounded-xl bg-slate-800/30 animate-pulse" />
                ))}
            </div>
        );
    }

    if (workers.length === 0) {
        return (
            <div className="text-center py-12 bg-slate-800/30 rounded-xl border border-slate-700/50">
                <Server className="h-12 w-12 text-slate-600 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-slate-400">No Workers Online</h3>
                <p className="text-sm text-slate-500 mt-1">
                    Start Celery workers to begin processing jobs
                </p>
                <code className="block mt-4 text-xs text-slate-500 bg-slate-900/50 px-4 py-2 rounded-lg max-w-xl mx-auto">
                    celery -A celery_config worker --queue=pdf_processing --include=celery_tasks
                </code>
            </div>
        );
    }

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {workers.map((worker) => (
                <WorkerCard key={worker.hostname} worker={worker} />
            ))}
        </div>
    );
}
