'use client';

import { AccountInfo, AppConfig } from '@/lib/api';

interface Props {
  config: AppConfig | null;
  account: AccountInfo | null;
  onAuthClick: () => void;
  onManageClick: () => void;
}

export default function Navbar({ account, onAuthClick, onManageClick }: Props) {
  const isLoggedIn = !!account;

  return (
    <nav className="sticky top-0 z-50 bg-white border-b border-gray-100 shadow-sm">
      <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
        <a href="/" className="flex items-center gap-2 font-bold text-gray-900 text-lg">
          <svg className="w-6 h-6 text-indigo-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
            <line x1="16" y1="17" x2="8" y2="17"/>
          </svg>
          ScanToText
        </a>

        <div className="flex items-center gap-4">
          <a href="#pricing" className="text-sm text-gray-500 hover:text-gray-900 transition-colors">Pricing</a>

          {isLoggedIn ? (
            <div className="flex items-center gap-2">
              <a
                href="/dashboard"
                className="text-sm text-gray-500 hover:text-indigo-600 transition-colors"
              >
                Dashboard
              </a>
              <div className="flex items-center gap-1.5 bg-gray-50 border border-gray-200 rounded-full px-3 py-1 text-sm">
                <svg className="w-3.5 h-3.5 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z"/>
                  <polyline points="13 2 13 9 20 9"/>
                </svg>
                <span className="text-gray-700 font-medium">{account.pages_used} / {account.page_limit}</span>
                <span className="text-gray-400">pages</span>
                {account.is_trial && account.trial_active && (
                  <span className="ml-1 px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700 text-xs font-semibold">
                    {account.trial_days_left}d trial
                  </span>
                )}
              </div>
              <button
                onClick={onManageClick}
                className="text-sm border border-gray-300 rounded-lg px-3 py-1 hover:bg-gray-50 transition-colors"
              >
                Manage
              </button>
            </div>
          ) : (
            <button
              onClick={onAuthClick}
              className="text-sm bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-1.5 font-medium transition-colors"
            >
              Free Trial
            </button>
          )}
        </div>
      </div>
    </nav>
  );
}
