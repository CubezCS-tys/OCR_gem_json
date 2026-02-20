export default function Footer() {
  return (
    <footer className="bg-gray-900 text-gray-400 py-10">
      <div className="max-w-5xl mx-auto px-4 text-center">
        <div className="flex items-center justify-center gap-2 mb-3">
          <svg className="w-5 h-5 text-indigo-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
            <line x1="16" y1="17" x2="8" y2="17"/>
          </svg>
          <span className="font-semibold text-white">ScanToText</span>
        </div>
        <p className="text-sm mb-2">Powered by Azure AI, Google Gemini &amp; Mistral</p>
        <p className="text-xs">
          <a href="/privacy" className="hover:text-white transition-colors">Privacy Policy</a>
          <span className="mx-2">·</span>
          <a href="/terms" className="hover:text-white transition-colors">Terms of Service</a>
        </p>
      </div>
    </footer>
  );
}
