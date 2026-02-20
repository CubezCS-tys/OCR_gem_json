'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { getToken, getEmail, clearAuth } from '@/lib/auth';
import { fetchDashboard, type DashboardData, type DashboardJob } from '@/lib/api';

// ── helpers ───────────────────────────────────────────────────────────────────
function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function fmtDate(epoch: number): string {
  return new Date(epoch * 1000).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function daysUntil(epoch: number): number {
  return Math.max(0, Math.ceil((epoch * 1000 - Date.now()) / 86_400_000));
}

// ── status badge ──────────────────────────────────────────────────────────────
function StatusBadge({ job }: { job: DashboardJob }) {
  if (job.is_expired)
    return <span className="px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-500">Expired</span>;
  if (job.status === 'done')
    return <span className="px-2 py-0.5 text-xs rounded-full bg-green-100 text-green-700">Done</span>;
  if (job.status === 'processing')
    return <span className="px-2 py-0.5 text-xs rounded-full bg-yellow-100 text-yellow-700">Processing</span>;
  if (job.status === 'error')
    return <span className="px-2 py-0.5 text-xs rounded-full bg-red-100 text-red-600">Error</span>;
  return <span className="px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-600">{job.status}</span>;
}

// ── job row ───────────────────────────────────────────────────────────────────
function JobRow({ job }: { job: DashboardJob }) {
  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
      <td className="py-3 px-4">
        <div className="font-medium text-gray-800 truncate max-w-[200px]" title={job.filename}>
          {job.filename}
        </div>
        <div className="text-xs text-gray-400 mt-0.5">{fmtBytes(job.file_size)}</div>
      </td>
      <td className="py-3 px-4 text-sm text-gray-600">{job.page_count}p</td>
      <td className="py-3 px-4">
        <StatusBadge job={job} />
      </td>
      <td className="py-3 px-4 text-sm text-gray-500">
        <span className={`capitalize ${job.type === 'pro' ? 'text-indigo-600 font-medium' : ''}`}>
          {job.type ?? 'free'}
        </span>
      </td>
      <td className="py-3 px-4 text-sm text-gray-500">{fmtDate(job.created_at)}</td>
      <td className="py-3 px-4 text-sm text-gray-400">
        {job.is_expired ? (
          <span>Expired</span>
        ) : job.type === 'pro' ? (
          <span className="text-green-600">{daysUntil(job.expires_at)}d left</span>
        ) : (
          <span>24 h</span>
        )}
      </td>
      <td className="py-3 px-4">
        {job.download_url ? (
          <a
            href={job.download_url}
            className="inline-flex items-center gap-1 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium rounded-lg transition-colors"
            download
          >
            ↓ Download
          </a>
        ) : (
          <span className="text-xs text-gray-400">
            {job.is_expired ? '—' : job.status !== 'done' ? '—' : 'File missing'}
          </span>
        )}
      </td>
    </tr>
  );
}

// ── main component ────────────────────────────────────────────────────────────
export default function DashboardClient() {
  const router = useRouter();
  const [data, setData]     = useState<DashboardData | null>(null);
  const [error, setError]   = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.push('/');
      return;
    }
    fetchDashboard(token)
      .then(setData)
      .catch((e: Error) => {
        if (e.message === 'unauthorized') {
          clearAuth();
          router.push('/');
        } else {
          setError(e.message);
        }
      })
      .finally(() => setLoading(false));
  }, [router]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="animate-pulse text-gray-400 text-lg">Loading dashboard…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-red-500">Error: {error}</div>
      </div>
    );
  }

  if (!data) return null;

  const usagePct = data.page_limit > 0 ? Math.min(100, (data.pages_used / data.page_limit) * 100) : 0;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Nav */}
      <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
        <Link href="/" className="text-xl font-bold text-indigo-600 tracking-tight">
          ScanToText
        </Link>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-500">{data.email}</span>
          <button
            onClick={() => { clearAuth(); router.push('/'); }}
            className="text-sm text-gray-500 hover:text-gray-800"
          >
            Sign out
          </button>
        </div>
      </nav>

      <main className="max-w-5xl mx-auto px-4 py-10 space-y-8">

        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-500 text-sm mt-1">Your conversion history and account usage.</p>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {/* Plan */}
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Plan</div>
            <div className="text-2xl font-bold text-gray-800">
              {data.is_subscribed ? 'Pro' : data.is_trial ? 'Trial' : 'Free'}
            </div>
            {data.is_trial && data.trial_days_left !== null && (
              <div className="text-xs text-yellow-600 mt-1">{data.trial_days_left} days remaining</div>
            )}
            {!data.is_active && (
              <Link href="/" className="mt-2 inline-block text-xs text-indigo-600 hover:underline">
                Upgrade →
              </Link>
            )}
          </div>

          {/* Pages used */}
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Pages Used</div>
            <div className="text-2xl font-bold text-gray-800">{data.pages_used.toLocaleString()}</div>
            {data.page_limit > 0 && (
              <>
                <div className="mt-2 bg-gray-100 rounded-full h-1.5">
                  <div
                    className="bg-indigo-500 h-1.5 rounded-full transition-all"
                    style={{ width: `${usagePct}%` }}
                  />
                </div>
                <div className="text-xs text-gray-400 mt-1">
                  {data.pages_remaining.toLocaleString()} of {data.page_limit.toLocaleString()} remaining
                </div>
              </>
            )}
          </div>

          {/* Jobs */}
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Total Jobs</div>
            <div className="text-2xl font-bold text-gray-800">{data.jobs.length}</div>
            <div className="text-xs text-gray-400 mt-1">
              {data.jobs.filter(j => !j.is_expired && j.download_url).length} available for download
            </div>
          </div>
        </div>

        {/* Job history table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-100">
            <h2 className="text-base font-semibold text-gray-800">Conversion History</h2>
            <p className="text-xs text-gray-400 mt-0.5">
              Pro conversions kept 30 days · Free conversions kept 24 hours
            </p>
          </div>

          {data.jobs.length === 0 ? (
            <div className="px-6 py-12 text-center text-gray-400 text-sm">
              No conversions yet.{' '}
              <Link href="/" className="text-indigo-600 hover:underline">Convert a document →</Link>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wider">
                    <th className="text-left py-3 px-4 font-medium">File</th>
                    <th className="text-left py-3 px-4 font-medium">Pages</th>
                    <th className="text-left py-3 px-4 font-medium">Status</th>
                    <th className="text-left py-3 px-4 font-medium">Tier</th>
                    <th className="text-left py-3 px-4 font-medium">Date</th>
                    <th className="text-left py-3 px-4 font-medium">Expires</th>
                    <th className="text-left py-3 px-4 font-medium">Download</th>
                  </tr>
                </thead>
                <tbody>
                  {data.jobs.map(job => <JobRow key={job.job_id} job={job} />)}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <p className="text-center text-xs text-gray-400">
          <Link href="/" className="hover:text-indigo-600 transition-colors">← Back to converter</Link>
        </p>
      </main>
    </div>
  );
}
