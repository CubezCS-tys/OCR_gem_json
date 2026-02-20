'use client';

interface Props {
  jobId: string;
  filename?: string;
  formats?: string[];
  onNew: () => void;
}

export default function ResultSection({ jobId, filename, formats, onNew }: Props) {
  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-10 text-center">
      <div className="flex justify-center mb-4">
        <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center">
          <svg className="w-8 h-8 text-emerald-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </div>
      </div>
      <h3 className="text-xl font-semibold text-gray-900 mb-1">Your document is ready</h3>
      {filename && <p className="text-sm text-gray-500 mb-3">{filename}</p>}

      {formats && formats.length > 0 && (
        <div className="flex flex-wrap justify-center gap-2 mb-6">
          {formats.map((f) => (
            <span key={f} className="px-3 py-1 bg-indigo-100 text-indigo-700 rounded-full text-xs font-semibold">{f}</span>
          ))}
        </div>
      )}

      <div className="flex flex-col sm:flex-row justify-center gap-3 mt-4">
        <a
          href={`/api/download/${jobId}`}
          download
          className="inline-flex items-center justify-center gap-2 px-6 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-semibold text-sm transition-colors"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          Download
        </a>
        <button
          onClick={onNew}
          className="inline-flex items-center justify-center gap-2 px-6 py-2.5 border border-gray-300 hover:bg-gray-50 text-gray-700 rounded-xl font-semibold text-sm transition-colors"
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
