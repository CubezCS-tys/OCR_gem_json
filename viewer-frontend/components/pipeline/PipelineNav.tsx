'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
    LayoutDashboard,
    ListTodo,
    Upload,
    Server,
    ChevronLeft,
    Activity
} from 'lucide-react';

const navItems = [
    { href: '/pipeline', label: 'Dashboard', icon: LayoutDashboard },
    { href: '/pipeline/jobs', label: 'Jobs', icon: ListTodo },
    { href: '/pipeline/submit', label: 'Submit', icon: Upload },
    { href: '/pipeline/workers', label: 'Workers', icon: Server },
];

export function PipelineNav() {
    const pathname = usePathname();

    return (
        <nav className="flex items-center gap-6 mb-6">
            <Link
                href="/"
                className="flex items-center gap-2 text-slate-400 hover:text-white transition-colors"
            >
                <ChevronLeft className="h-4 w-4" />
                <span className="text-sm">Back to Viewer</span>
            </Link>

            <div className="h-6 w-px bg-slate-700" />

            <div className="flex items-center gap-2">
                <Activity className="h-5 w-5 text-blue-400" />
                <span className="font-semibold text-white">Pipeline Control</span>
            </div>

            <div className="flex-1" />

            <div className="flex items-center gap-1 bg-slate-800/50 rounded-lg p-1">
                {navItems.map((item) => {
                    const isActive = pathname === item.href;
                    return (
                        <Link
                            key={item.href}
                            href={item.href}
                            className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors ${isActive
                                    ? 'bg-blue-500/20 text-blue-400'
                                    : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
                                }`}
                        >
                            <item.icon className="h-4 w-4" />
                            <span>{item.label}</span>
                        </Link>
                    );
                })}
            </div>
        </nav>
    );
}
