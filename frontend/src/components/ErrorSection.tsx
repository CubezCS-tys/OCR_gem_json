'use client';

interface Props {
  message: string;
  onRetry: () => void;
}

export default function ErrorSection({ message, onRetry }: Props) {
  const isRateLimited = message === 'RATE_LIMITED';

  return (
    <div className="bg-white rounded-2xl border border-parchment-dark p-10 text-center shadow-sm">
      <div className="flex justify-center mb-4">
        <div className={`w-16 h-16 ${isRateLimited ? 'bg-amber-100' : 'bg-red-100'} rounded-full flex items-center justify-center`}>
          {isRateLimited ? (
            <svg className="w-8 h-8 text-amber-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"/>
              <polyline points="12 6 12 12 16 14"/>
            </svg>
          ) : (
            <svg className="w-8 h-8 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"/>
              <line x1="12" y1="8" x2="12" y2="12"/>
              <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
          )}
        </div>
      </div>

      {isRateLimited ? (
        <>
          <h3 className="text-xl font-semibold text-ink mb-2">Free limit reached</h3>
          <p className="text-sm text-gray-500 mb-6">
            You&apos;ve used your free conversions for this hour.<br/>
            Wait an hour to try again, or sign up for unlimited access.
          </p>
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <a
              href="/?signup=1"
              className="px-6 py-2.5 bg-ember hover:bg-ember-dark text-white rounded-xl font-semibold text-sm transition-colors"
            >
              Sign Up — It&apos;s Free
            </a>
            <button
              onClick={onRetry}
              className="px-6 py-2.5 bg-parchment hover:bg-parchment-dark text-ink rounded-xl font-semibold text-sm transition-colors"
            >
              Try Again Later
            </button>
          </div>
        </>
      ) : (
        <>
          <h3 className="text-xl font-semibold text-ink mb-2">Processing failed</h3>
          <p className="text-sm text-gray-500 mb-6">{message}</p>
          <button
            onClick={onRetry}
            className="px-6 py-2.5 bg-ink hover:bg-ink-light text-white rounded-xl font-semibold text-sm transition-colors"
          >
            Try Again
          </button>
        </>
      )}
    </div>
  );
}
