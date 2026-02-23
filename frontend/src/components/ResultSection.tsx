'use client';

interface Props {
  jobId: string;
  filename?: string;
  formats?: string[];
  isPro?: boolean;
  onNew: () => void;
}

export default function ResultSection({ jobId, filename, formats, isPro, onNew }: Props) {
  return (
    <div className="bg-white rounded-2xl border border-parchment-dark p-10 text-center shadow-sm">
      <div className="flex justify-center mb-4">
        <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center">
          <svg className="w-8 h-8 text-green-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </div>
      </div>
      <h3 className="text-xl font-semibold text-ink mb-1">Your document is ready</h3>
      {filename && <p className="text-sm text-gray-400 mb-3">{filename}</p>}

      {formats && formats.length > 0 && (
        <div className="flex flex-wrap justify-center gap-2 mb-6">
          {formats.map((f) => (
            <span key={f} className="px-3 py-1 bg-ember-light text-ember-muted rounded-full text-xs font-semibold">{f}</span>
          ))}
        </div>
      )}

      <div className="flex flex-col sm:flex-row justify-center gap-3 mt-4">
        <a
          href={`/api/download/${jobId}`}
          download
          className="inline-flex items-center justify-center gap-2 px-6 py-2.5 bg-ember hover:bg-ember-dark text-white rounded-xl font-semibold text-sm transition-colors"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          Download
        </a>
        {isPro && (
          <a
            href={`/api/corrections/tool?doc_id=${jobId}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center gap-2 px-6 py-2.5 border border-parchment-dark hover:bg-parchment text-ink rounded-xl font-semibold text-sm transition-colors"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
            Correct
          </a>
        )}
        <button
          onClick={onNew}
          className="inline-flex items-center justify-center gap-2 px-6 py-2.5 border border-parchment-dark hover:bg-parchment text-ink rounded-xl font-semibold text-sm transition-colors"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="1 4 1 10 7 10"/>
            <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>
          </svg>
          New File
        </button>
      </div>
    </div>
  );
}
