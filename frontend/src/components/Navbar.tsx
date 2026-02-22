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
    <nav className="sticky top-0 z-50 bg-ink border-b border-ink-light">
      <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
        <a href="/" className="flex items-center gap-2 font-bold text-white text-lg tracking-tight">
          <svg className="w-6 h-6 text-ember" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
            <line x1="16" y1="17" x2="8" y2="17"/>
          </svg>
          ScanToText
        </a>

        <div className="flex items-center gap-4">
          <a href="#pricing" className="text-sm text-gray-400 hover:text-white transition-colors">Pricing</a>

          {isLoggedIn ? (
            <div className="flex items-center gap-2">
              <a
                href="/dashboard"
                className="text-sm text-gray-400 hover:text-white transition-colors"
              >
                Dashboard
              </a>
              <div className="flex items-center gap-1.5 bg-ink-light border border-white/10 rounded-full px-3 py-1 text-sm">
                <svg className="w-3.5 h-3.5 text-gray-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z"/>
                  <polyline points="13 2 13 9 20 9"/>
                </svg>
                <span className="text-white font-medium">{account.pages_used} / {account.page_limit}</span>
                <span className="text-gray-500">pages</span>
                {account.is_trial && account.trial_active && (
                  <span className="ml-1 px-1.5 py-0.5 rounded-full bg-ember/20 text-ember text-xs font-semibold">
                    {account.trial_days_left}d trial
                  </span>
                )}
              </div>
              {account.is_subscribed && (
                <button
                  onClick={onManageClick}
                  className="text-sm border border-white/20 text-gray-300 hover:text-white hover:border-white/40 rounded-lg px-3 py-1 transition-colors"
                >
                  Manage
                </button>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <button
                onClick={onAuthClick}
                className="text-sm text-gray-400 hover:text-white transition-colors"
              >
                Sign In
              </button>
              <button
                onClick={onAuthClick}
                className="text-sm bg-ember hover:bg-ember-dark text-white rounded-lg px-4 py-1.5 font-semibold transition-colors"
              >
                Free Trial
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
}
