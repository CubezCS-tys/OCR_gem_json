'use client';

interface Props {
  priceDisplay: string;
  onSubscribe: () => void;
}

export default function PricingSection({ priceDisplay, onSubscribe }: Props) {
  return (
    <section id="pricing" className="py-20 bg-white">
      <div className="max-w-5xl mx-auto px-4">
        <h2 className="text-3xl font-bold text-center text-ink mb-2">Simple, transparent pricing</h2>
        <p className="text-center text-gray-400 mb-14">Start free. Go Pro when you need every format.</p>

        <div className="grid md:grid-cols-2 gap-6 max-w-2xl mx-auto">
          {/* Free */}
          <div className="bg-white border border-parchment-dark rounded-2xl p-8">
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

          {/* Pro — ink card */}
          <div className="bg-ink rounded-2xl p-8 relative shadow-lg">
            <div className="absolute -top-3.5 left-1/2 -translate-x-1/2 px-3 py-1 bg-ember text-white text-xs font-bold rounded-full tracking-wide">
              Recommended
            </div>
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
            <button
              onClick={onSubscribe}
              className="w-full py-3 bg-ember hover:bg-ember-dark text-white rounded-xl font-semibold transition-colors"
            >
              Subscribe Now
            </button>
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
