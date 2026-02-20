'use client';

import { useEffect, useRef } from 'react';

interface Props {
  title: string;
  message: string;
  durationMs: number;
}

export default function ProcessingSection({ title, message, durationMs }: Props) {
  const barRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!barRef.current) return;
    const bar = barRef.current;
    bar.style.width = '0%';
    const start = Date.now();
    const max = 90;
    const iv = setInterval(() => {
      const pct = Math.min(((Date.now() - start) / durationMs) * max, max);
      bar.style.width = `${pct}%`;
      if (pct >= max) clearInterval(iv);
    }, 200);
    return () => clearInterval(iv);
  }, [durationMs]);

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-10 text-center">
      <div className="flex justify-center mb-6">
        <div className="relative w-16 h-16">
          <svg className="w-16 h-16 -rotate-90" viewBox="0 0 60 60">
            <circle className="ring-bg" cx="30" cy="30" r="26"/>
            <circle className="ring-fg" cx="30" cy="30" r="26"/>
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <svg className="w-6 h-6 text-indigo-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8"/>
              <line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
          </div>
        </div>
      </div>
      <h3 className="text-lg font-semibold text-gray-900 mb-1">{title}</h3>
      <p className="text-sm text-gray-500 mb-6">{message}</p>
      <div className="progress-bar-wrap">
        <div ref={barRef} className="progress-bar" />
      </div>
    </div>
  );
}
