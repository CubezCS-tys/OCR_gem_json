'use client';

import { useState, useRef, useEffect } from 'react';

interface Props {
  priceDisplay: string;
  onSubscribe: () => void;
}

export default function PricingSection({ priceDisplay, onSubscribe }: Props) {
  const [showContact, setShowContact] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    function handle(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setShowContact(false);
      }
    }
    if (showContact) document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, [showContact]);

  return (
    <section id="pricing" className="py-20 bg-white">
      <div className="max-w-5xl mx-auto px-4">
        <h2 className="text-3xl font-bold text-center text-ink mb-2">Simple, transparent pricing</h2>
        <p className="text-center text-gray-400 mb-14">Start free. Go Pro when you need every format.</p>

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-6">
          {/* Free */}
          <div className="bg-white border border-parchment-dark rounded-2xl p-7 flex flex-col">
            <div>
              <h3 className="text-xl font-bold text-ink mb-1">Free</h3>
              <div className="text-4xl font-bold text-ink mb-0.5">£0</div>
              <p className="text-sm text-gray-400 mb-6">forever</p>
              <hr className="border-parchment-dark mb-5"/>
              <ul className="space-y-2.5 text-sm">
                {[
                  { text: 'Searchable PDF output', on: true },
                  { text: '5 conversions / hour', on: true },
                  { text: 'Max 100 pages per document', on: true },
                  { text: 'Arabic, English & French', on: true },
                  { text: 'Pixel-perfect HTML', on: false },
                  { text: 'Semantic HTML', on: false },
                  { text: 'Markdown + images', on: false },
                  { text: 'Extracted figures', on: false },
                ].map((f) => (
                  <li key={f.text} className={`flex items-center gap-2 ${f.on ? 'text-ink' : 'text-gray-300'}`}>
                    <svg className={`w-4 h-4 flex-shrink-0 ${f.on ? 'text-green-500' : 'text-gray-200'}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      {f.on ? <polyline points="20 6 9 17 4 12"/> : <line x1="18" y1="12" x2="6" y2="12"/>}
                    </svg>
                    {f.text}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Free Trial */}
          <div className="bg-amber-50 border border-amber-200 rounded-2xl p-7 flex flex-col relative">
            <div className="absolute -top-3.5 left-1/2 -translate-x-1/2 px-3 py-1 bg-amber-400 text-white text-xs font-bold rounded-full tracking-wide whitespace-nowrap">
              No card needed
            </div>
            <div className="flex-1">
              <h3 className="text-xl font-bold text-ink mb-1">Free Trial</h3>
              <div className="text-4xl font-bold text-ink mb-0.5">7 days</div>
              <p className="text-sm text-gray-500 mb-6">full Pro access</p>
              <hr className="border-amber-200 mb-5"/>
              <ul className="space-y-2.5 text-sm mb-6">
                {[
                  'All Pro formats included',
                  '1,000 pages to spend',
                  'No credit card required',
                  'Pixel-perfect HTML',
                  'Semantic HTML (Gemini)',
                  'Markdown + images',
                  'ZIP bundle download',
                ].map((f) => (
                  <li key={f} className="flex items-center gap-2 text-ink">
                    <svg className="w-4 h-4 flex-shrink-0 text-amber-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <polyline points="20 6 9 17 4 12"/>
                    </svg>
                    {f}
                  </li>
                ))}
              </ul>
            </div>
            <button
              onClick={onSubscribe}
              className="w-full py-3 bg-amber-400 hover:bg-amber-500 text-white rounded-xl font-semibold transition-colors"
            >
              Start Free Trial
            </button>
          </div>

          {/* Pro — ink card */}
          <div className="bg-ink rounded-2xl p-7 relative shadow-lg flex flex-col">
            <div className="absolute -top-3.5 left-1/2 -translate-x-1/2 px-3 py-1 bg-ember text-white text-xs font-bold rounded-full tracking-wide">
              Recommended
            </div>
            <div className="flex-1">
              <h3 className="text-xl font-bold text-white mb-1">Pro</h3>
              <div className="text-4xl font-bold text-white mb-0.5">{priceDisplay}</div>
              <p className="text-sm text-gray-400 mb-1">per month</p>
              <p className="text-sm font-semibold text-ember mb-6">2,000 pages included</p>
              <hr className="border-white/10 mb-5"/>
              <ul className="space-y-2.5 text-sm mb-6">
                {[
                  'Everything in Free',
                  'Pixel-perfect HTML (Azure)',
                  'Semantic HTML (Gemini AI)',
                  'Markdown + images (Mistral)',
                  'Extracted figures',
                  'ZIP bundle download',
                  'Priority processing',
                ].map((f) => (
                  <li key={f} className="flex items-center gap-2 text-gray-300">
                    <svg className="w-4 h-4 flex-shrink-0 text-ember" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <polyline points="20 6 9 17 4 12"/>
                    </svg>
                    {f}
                  </li>
                ))}
              </ul>
            </div>
            <button
              onClick={onSubscribe}
              className="w-full py-3 bg-ember hover:bg-ember-dark text-white rounded-xl font-semibold transition-colors"
            >
              Subscribe Now
            </button>
          </div>

          {/* Enterprise */}
          <div className="bg-ink-dark border border-ink-light rounded-2xl p-7 flex flex-col">
            <div className="flex-1">
              <h3 className="text-xl font-bold text-white mb-1">Enterprise</h3>
              <div className="text-4xl font-bold text-white mb-0.5">Custom</div>
              <p className="text-sm text-gray-400 mb-6">tailored to your volume</p>
              <hr className="border-white/10 mb-5"/>
              <ul className="space-y-2.5 text-sm mb-6">
                {[
                  'Unlimited pages',
                  'Dedicated processing queue',
                  'Custom SLA & uptime',
                  'API access & webhooks',
                  'White-label output',
                  'Onboarding & support',
                  'Invoice billing',
                ].map((f) => (
                  <li key={f} className="flex items-center gap-2 text-gray-300">
                    <svg className="w-4 h-4 flex-shrink-0 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <polyline points="20 6 9 17 4 12"/>
                    </svg>
                    {f}
                  </li>
                ))}
              </ul>
            </div>
            <div className="relative" ref={popoverRef}>
              <button
                onClick={() => setShowContact((v) => !v)}
                className="w-full py-3 border border-white/20 hover:border-white/50 text-white rounded-xl font-semibold transition-colors"
              >
                Contact Sales
              </button>
              {showContact && (
                <div className="absolute bottom-full mb-2 right-0 w-72 bg-white rounded-xl shadow-xl border border-parchment-dark overflow-hidden z-10">
                  <a
                    href="tel:+447511005894"
                    className="flex items-center gap-3 px-4 py-3.5 hover:bg-parchment transition-colors group"
                  >
                    <span className="w-8 h-8 rounded-full bg-ink/10 flex items-center justify-center flex-shrink-0">
                      <svg className="w-4 h-4 text-ink" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07A19.5 19.5 0 013.1 10.77a19.79 19.79 0 01-3.07-8.67A2 2 0 012 0h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L6.09 7.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 14.92z"/>
                      </svg>
                    </span>
                    <div>
                      <p className="text-xs text-gray-400 font-medium">Phone</p>
                      <p className="text-sm font-semibold text-ink whitespace-nowrap">+44 7511 005894</p>
                    </div>
                  </a>
                  {/* Email option — re-enable when ready
                  <div className="border-t border-parchment-dark"/>
                  <a
                    href="mailto:ysolta1969@gmail.com"
                    className="flex items-center gap-3 px-4 py-3.5 hover:bg-parchment transition-colors group"
                  >
                    <span className="w-8 h-8 rounded-full bg-ink/10 flex items-center justify-center flex-shrink-0">
                      <svg className="w-4 h-4 text-ink" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
                        <polyline points="22,6 12,13 2,6"/>
                      </svg>
                    </span>
                    <div>
                      <p className="text-xs text-gray-400 font-medium">Email</p>
                      <p className="text-sm font-semibold text-ink whitespace-nowrap">ysolta1969@gmail.com</p>
                    </div>
                  </a>
                  */}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Engines */}
        <div className="mt-16 text-center">
          <h3 className="text-xl font-bold text-ink mb-8">Powered by 3 AI engines</h3>
          <div className="grid md:grid-cols-3 gap-6">
            {[
              { name: 'Azure Document Intelligence', desc: 'Industry-leading OCR with word-level bounding boxes, table extraction, and reading order detection.' },
              { name: 'Google Gemini', desc: 'Semantic classification — headings, footnotes, verses, body text — for structured HTML output.' },
              { name: 'Mistral AI', desc: 'Rich markdown extraction with embedded images, tables, and multi-language support.' },
            ].map((e) => (
              <div key={e.name} className="bg-parchment border border-parchment-dark rounded-xl p-6 text-left">
                <p className="font-semibold text-ink mb-2">{e.name}</p>
                <p className="text-sm text-gray-500 leading-relaxed">{e.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
