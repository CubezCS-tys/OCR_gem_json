'use client';

import { useState } from 'react';
import { AppConfig, AccountInfo } from '@/lib/api';

interface Props {
  filename: string;
  fileSizeMb: string;
  pageCount: number;
  uploading: boolean;
  config: AppConfig | null;
  account: AccountInfo | null;
  onRemove: () => void;
  onConvert: (tier: 'free' | 'pro', formats?: string) => void;
  onNeedAuth: () => void;
}

const FORMAT_OPTIONS = [
  { value: 'searchable_pdf', label: 'Searchable PDF', defaultOn: true },
  { value: 'pixel_html',     label: 'Pixel HTML',     defaultOn: true },
  { value: 'semantic_html',  label: 'Semantic HTML',  defaultOn: false, slow: true },
  { value: 'markdown',       label: 'Mistral MD',     defaultOn: true },
];

export default function FileSection({
  filename, fileSizeMb, pageCount, uploading,
  config, account, onRemove, onConvert, onNeedAuth,
}: Props) {
  const [checked, setChecked] = useState<Record<string, boolean>>(
    Object.fromEntries(FORMAT_OPTIONS.map((f) => [f.value, f.defaultOn])),
  );

  const freeMaxPages = config?.free_max_pages ?? 5;
  const overFreeLimit = !account && pageCount > freeMaxPages;

  function toggle(v: string) {
    setChecked((prev) => ({ ...prev, [v]: !prev[v] }));
  }

  function handleProClick() {
    if (!account) { onNeedAuth(); return; }
    const selected = Object.entries(checked)
      .filter(([, on]) => on)
      .map(([v]) => v);
    if (!selected.length) { alert('Select at least one output format.'); return; }
    onConvert('pro', selected.join(','));
  }

  const proNote = !account
    ? '7-day free trial available — no card needed'
    : `Will use ${pageCount} of your remaining pages`;

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
      {/* File header */}
      <div className="flex items-center gap-3 mb-6 pb-5 border-b border-gray-100">
        <div className="w-10 h-10 bg-indigo-50 rounded-lg flex items-center justify-center flex-shrink-0">
          <svg className="w-5 h-5 text-indigo-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-medium text-gray-900 truncate">{filename}</p>
          <p className="text-sm text-gray-500">{fileSizeMb} MB</p>
        </div>
        <button
          onClick={onRemove}
          className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors text-gray-400 hover:text-gray-600"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      {/* Action cards */}
      <div className="grid md:grid-cols-2 gap-4">
        {/* Free */}
        <div className="border border-gray-200 rounded-xl p-5 flex flex-col">
          <div className="flex items-center gap-2 mb-2">
            <span className="px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 text-xs font-semibold uppercase tracking-wide">Free</span>
            <h3 className="font-semibold text-gray-900">Searchable PDF</h3>
          </div>
          <p className="text-sm text-gray-500 mb-3">Text-selectable PDF with Ctrl+F search and copy/paste.</p>
          <ul className="text-sm text-gray-600 space-y-1.5 mb-4">
            {['Text search & copy', 'No sign-up needed', `Up to ${freeMaxPages} pages`].map((f) => (
              <li key={f} className="flex items-center gap-2">
                <svg className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                {f}
              </li>
            ))}
          </ul>
          {overFreeLimit && (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-3">
              This document has <strong>{pageCount} pages</strong> — free tier is limited to {freeMaxPages}. Use Pro or sign in.
            </p>
          )}
          <button
            disabled={uploading || overFreeLimit}
            onClick={() => onConvert('free')}
            className="mt-auto w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed text-white font-semibold text-sm transition-colors"
          >
            {uploading ? 'Uploading…' : overFreeLimit ? `Over ${freeMaxPages}-page limit` : 'Convert — Free'}
          </button>
        </div>

        {/* Pro */}
        <div className="border-2 border-amber-300 rounded-xl p-5 flex flex-col bg-amber-50/30">
          <div className="flex items-center gap-2 mb-2">
            <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 text-xs font-semibold uppercase tracking-wide">Pro</span>
            <h3 className="font-semibold text-gray-900">All Formats</h3>
          </div>
          <p className="text-sm text-gray-500 mb-3">Pick the outputs you need.</p>

          <div className="flex flex-wrap gap-2 mb-3">
            {FORMAT_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className={`fmt-chip inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium cursor-pointer transition-all select-none ${
                  checked[opt.value]
                    ? 'border-violet-400 bg-violet-100 text-violet-800'
                    : 'border-gray-300 bg-gray-50 text-gray-500'
                }`}
              >
                <input
                  type="checkbox"
                  checked={checked[opt.value]}
                  onChange={() => toggle(opt.value)}
                  className="hidden"
                />
                {opt.label}
                {opt.slow && <em className="opacity-60 not-italic text-[10px]">(slow)</em>}
              </label>
            ))}
          </div>

          <p className="text-xs text-gray-500 mb-3">
            This document: <strong>{pageCount} pages</strong>
          </p>

          <button
            disabled={uploading}
            onClick={handleProClick}
            className="mt-auto w-full py-2.5 rounded-xl bg-amber-500 hover:bg-amber-600 disabled:opacity-60 disabled:cursor-not-allowed text-white font-semibold text-sm transition-colors"
          >
            {uploading ? 'Uploading…' : 'Convert — Pro'}
          </button>
          <p className="text-xs text-center mt-2 text-violet-600">{proNote}</p>
        </div>
      </div>
    </div>
  );
}
