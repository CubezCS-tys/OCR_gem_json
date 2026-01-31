'use client';

import { StatsInfo } from '@/lib/pipeline';
import { Activity, CheckCircle2, XCircle, Clock, Loader2 } from 'lucide-react';

interface StatsCardsProps {
    stats: StatsInfo | null;
    workersOnline: number;
    queueDepth: number;
    isLoading?: boolean;
}

export function StatsCards({ stats, workersOnline, queueDepth, isLoading }: StatsCardsProps) {
    const cards = [
        {
            title: 'Workers Online',
            value: workersOnline,
            icon: Activity,
            color: workersOnline > 0 ? 'text-emerald-400' : 'text-red-400',
            bgColor: workersOnline > 0 ? 'bg-emerald-500/10' : 'bg-red-500/10',
        },
        {
            title: 'Queue Depth',
            value: queueDepth,
            icon: Clock,
            color: queueDepth > 10 ? 'text-amber-400' : 'text-blue-400',
            bgColor: queueDepth > 10 ? 'bg-amber-500/10' : 'bg-blue-500/10',
        },
        {
            title: 'Completed',
            value: stats?.completed_jobs ?? 0,
            icon: CheckCircle2,
            color: 'text-emerald-400',
            bgColor: 'bg-emerald-500/10',
        },
        {
            title: 'Failed',
            value: stats?.failed_jobs ?? 0,
            icon: XCircle,
            color: stats?.failed_jobs ? 'text-red-400' : 'text-slate-400',
            bgColor: stats?.failed_jobs ? 'bg-red-500/10' : 'bg-slate-500/10',
        },
    ];

    return (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {cards.map((card) => (
                <div
                    key={card.title}
                    className="relative overflow-hidden rounded-xl bg-slate-800/50 backdrop-blur-sm border border-slate-700/50 p-4 transition-all hover:bg-slate-800/70 hover:border-slate-600/50"
                >
                    <div className="flex items-center justify-between">
                        <div>
                            <p className="text-sm text-slate-400">{card.title}</p>
                            <p className="text-2xl font-bold text-white mt-1">
                                {isLoading ? (
                                    <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
                                ) : (
                                    card.value
                                )}
                            </p>
                        </div>
                        <div className={`p-3 rounded-lg ${card.bgColor}`}>
                            <card.icon className={`h-6 w-6 ${card.color}`} />
                        </div>
                    </div>

                    {/* Decorative gradient */}
                    <div className={`absolute bottom-0 left-0 right-0 h-1 ${card.bgColor}`} />
                </div>
            ))}
        </div>
    );
}
