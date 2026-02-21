'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import {
  adminLogin,
  fetchAdminStats,
  fetchAdminUsers,
  fetchAdminJobs,
  AdminStats,
  AdminUser,
  AdminUsersPage,
  AdminJobsPage,
} from '@/lib/api';

// ── Helpers ───────────────────────────────────────────────────────────────────

const TOKEN_KEY = 'adminToken';

function fmtDate(epoch: number): string {
  if (!epoch) return '—';
  return new Date(epoch * 1000).toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
  });
}

function fmtDateShort(epoch: number): string {
  if (!epoch) return '—';
  return new Date(epoch * 1000).toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short',
  });
}

function PlanBadge({ user }: { user: AdminUser }) {
  if (user.is_subscribed)
    return (
      <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-ember/20 text-ember">
        Pro
      </span>
    );
  if (user.trial_active)
    return (
      <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-700">
        Trial
      </span>
    );
  return (
    <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-gray-100 text-gray-500">
      Free
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    done:       'bg-green-100 text-green-700',
    error:      'bg-red-100 text-red-700',
    processing: 'bg-blue-100 text-blue-700',
    uploaded:   'bg-gray-100 text-gray-600',
  };
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${map[status] ?? 'bg-gray-100 text-gray-500'}`}>
      {status}
    </span>
  );
}

function StatCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="bg-white border border-parchment-dark rounded-xl p-5">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">{label}</p>
      <p className="text-3xl font-bold text-ink">{value.toLocaleString()}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

function Pagination({
  page,
  pages,
  onChange,
}: {
  page: number;
  pages: number;
  onChange: (p: number) => void;
}) {
  if (pages <= 1) return null;
  return (
    <div className="flex items-center gap-2 mt-4 justify-end text-sm">
      <button
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
        className="px-3 py-1 rounded-lg border border-parchment-dark text-ink disabled:opacity-40 hover:border-ember transition-colors"
      >
        ← Prev
      </button>
      <span className="text-gray-500">
        {page} / {pages}
      </span>
      <button
        disabled={page >= pages}
        onClick={() => onChange(page + 1)}
        className="px-3 py-1 rounded-lg border border-parchment-dark text-ink disabled:opacity-40 hover:border-ember transition-colors"
      >
        Next →
      </button>
    </div>
  );
}

// ── Bar chart (pure CSS, no npm dep) ─────────────────────────────────────────

function DailyChart({ data }: { data: { date: string; count: number }[] }) {
  const max = Math.max(...data.map((d) => d.count), 1);
  return (
    <div className="bg-white border border-parchment-dark rounded-xl p-5">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-4">
        Daily conversions — last 14 days
      </p>
      <div className="flex items-end gap-1 h-32">
        {data.map((d) => {
          const pct = Math.round((d.count / max) * 100);
          const label = d.date.slice(5); // MM-DD
          return (
            <div key={d.date} className="flex-1 flex flex-col items-center gap-1 group">
              <span className="text-[10px] text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity">
                {d.count}
              </span>
              <div
                className="w-full rounded-t bg-ember/70 hover:bg-ember transition-colors"
                style={{ height: `${Math.max(pct, d.count > 0 ? 4 : 0)}%` }}
                title={`${d.date}: ${d.count} jobs`}
              />
              <span className="text-[9px] text-gray-400 rotate-45 origin-left mt-1 whitespace-nowrap">
                {label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Tabs ─────────────────────────────────────────────────────────────────────

type Tab = 'overview' | 'users' | 'jobs' | 'payments';

// ── Overview tab ─────────────────────────────────────────────────────────────

function OverviewTab({ token }: { token: string }) {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [err, setErr]     = useState('');

  useEffect(() => {
    fetchAdminStats(token)
      .then(setStats)
      .catch((e) => setErr(e.message));
  }, [token]);

  if (err) return <p className="text-red-600 text-sm">{err}</p>;
  if (!stats) return <p className="text-gray-400 text-sm">Loading…</p>;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <StatCard label="Total Users"     value={stats.total_users} />
        <StatCard label="Paid"            value={stats.subscribed} />
        <StatCard label="Trials"          value={stats.trial_users} />
        <StatCard label="Total Jobs"      value={stats.total_jobs}
                  sub={`${stats.anon_jobs} anonymous`} />
        <StatCard label="Pages Processed" value={stats.total_pages_processed} />
      </div>
      <DailyChart data={stats.daily_jobs} />
    </div>
  );
}

// ── Users tab ─────────────────────────────────────────────────────────────────

function UsersTab({ token }: { token: string }) {
  const [data, setData]   = useState<AdminUsersPage | null>(null);
  const [page, setPage]   = useState(1);
  const [q, setQ]         = useState('');
  const [search, setSearch] = useState('');
  const [err, setErr]     = useState('');
  const searchTimer       = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback((p: number, sq: string) => {
    setErr('');
    fetchAdminUsers(token, p, sq)
      .then(setData)
      .catch((e) => setErr(e.message));
  }, [token]);

  useEffect(() => { load(page, search); }, [load, page, search]);

  function handleQ(v: string) {
    setQ(v);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => {
      setPage(1);
      setSearch(v);
    }, 400);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <input
          type="text"
          value={q}
          onChange={(e) => handleQ(e.target.value)}
          placeholder="Search by email…"
          className="border border-parchment-dark rounded-lg px-3 py-2 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-ember/40 bg-white"
        />
        {data && (
          <span className="text-xs text-gray-400">{data.total.toLocaleString()} users</span>
        )}
      </div>
      {err && <p className="text-red-600 text-sm">{err}</p>}
      {data && (
        <>
          <div className="overflow-x-auto rounded-xl border border-parchment-dark">
            <table className="w-full text-sm">
              <thead className="bg-parchment-dark text-xs text-gray-500 uppercase tracking-wider">
                <tr>
                  {['Email', 'Plan', 'Pages Used', 'Page Limit', 'Trial Expires', 'Joined', 'Stripe ID'].map((h) => (
                    <th key={h} className="px-4 py-3 text-left font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-parchment-dark bg-white">
                {data.users.map((u) => (
                  <tr key={u.id} className="hover:bg-parchment/50 transition-colors">
                    <td className="px-4 py-3 font-medium text-ink max-w-[200px] truncate">{u.email}</td>
                    <td className="px-4 py-3"><PlanBadge user={u} /></td>
                    <td className="px-4 py-3 tabular-nums">{u.pages_used}</td>
                    <td className="px-4 py-3 tabular-nums">{u.page_limit}</td>
                    <td className="px-4 py-3 text-gray-500">{u.trial_expires ? fmtDate(u.trial_expires) : '—'}</td>
                    <td className="px-4 py-3 text-gray-500">{fmtDate(u.created_at)}</td>
                    <td className="px-4 py-3 text-gray-400 font-mono text-xs truncate max-w-[120px]">
                      {u.stripe_customer_id
                        ? <a href={`https://dashboard.stripe.com/customers/${u.stripe_customer_id}`} target="_blank" rel="noreferrer" className="text-ember hover:underline">{u.stripe_customer_id}</a>
                        : '—'}
                    </td>
                  </tr>
                ))}
                {data.users.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-gray-400">No users found</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pages={data.pages} onChange={setPage} />
        </>
      )}
    </div>
  );
}

// ── Jobs tab ──────────────────────────────────────────────────────────────────

function JobsTab({ token }: { token: string }) {
  const [data, setData]       = useState<AdminJobsPage | null>(null);
  const [page, setPage]       = useState(1);
  const [statusFilter, setStatusFilter] = useState('');
  const [err, setErr]         = useState('');

  const load = useCallback((p: number, sf: string) => {
    setErr('');
    fetchAdminJobs(token, p, { status: sf })
      .then(setData)
      .catch((e) => setErr(e.message));
  }, [token]);

  useEffect(() => { load(page, statusFilter); }, [load, page, statusFilter]);

  function changeStatus(v: string) {
    setStatusFilter(v);
    setPage(1);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <select
          value={statusFilter}
          onChange={(e) => changeStatus(e.target.value)}
          className="border border-parchment-dark rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-ember/40"
        >
          <option value="">All statuses</option>
          <option value="done">Done</option>
          <option value="error">Error</option>
          <option value="processing">Processing</option>
          <option value="uploaded">Uploaded</option>
        </select>
        {data && (
          <span className="text-xs text-gray-400">{data.total.toLocaleString()} jobs</span>
        )}
      </div>
      {err && <p className="text-red-600 text-sm">{err}</p>}
      {data && (
        <>
          <div className="overflow-x-auto rounded-xl border border-parchment-dark">
            <table className="w-full text-sm">
              <thead className="bg-parchment-dark text-xs text-gray-500 uppercase tracking-wider">
                <tr>
                  {['Filename', 'User', 'Pages', 'Tier', 'Status', 'Date', 'Retention'].map((h) => (
                    <th key={h} className="px-4 py-3 text-left font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-parchment-dark bg-white">
                {data.jobs.map((j) => (
                  <tr key={j.job_id} className="hover:bg-parchment/50 transition-colors">
                    <td className="px-4 py-3 font-medium text-ink max-w-[180px] truncate" title={j.filename}>{j.filename}</td>
                    <td className="px-4 py-3 text-gray-500 max-w-[160px] truncate">{j.user_email ?? <span className="text-gray-300">anon</span>}</td>
                    <td className="px-4 py-3 tabular-nums">{j.page_count}</td>
                    <td className="px-4 py-3 text-gray-500 capitalize">{j.type ?? '—'}</td>
                    <td className="px-4 py-3"><StatusBadge status={j.status} /></td>
                    <td className="px-4 py-3 text-gray-500">{fmtDateShort(j.created_at)}</td>
                    <td className="px-4 py-3 text-gray-400">{j.retention_days}d</td>
                  </tr>
                ))}
                {data.jobs.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-gray-400">No jobs found</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pages={data.pages} onChange={setPage} />
        </>
      )}
    </div>
  );
}

// ── Payments tab ──────────────────────────────────────────────────────────────

function PaymentsTab({ token }: { token: string }) {
  const [data, setData] = useState<AdminUsersPage | null>(null);
  const [page, setPage] = useState(1);
  const [err, setErr]   = useState('');

  const load = useCallback((p: number) => {
    setErr('');
    // Re-use users endpoint and filter client-side to subscribed users
    fetchAdminUsers(token, p, '')
      .then((d) => {
        // Filter to subscribed only for display
        setData({ ...d, users: d.users.filter((u) => u.is_subscribed) });
      })
      .catch((e) => setErr(e.message));
  }, [token]);

  useEffect(() => { load(page); }, [load, page]);

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-400">Showing paid subscribers only. Click a Stripe ID to open in Stripe Dashboard.</p>
      {err && <p className="text-red-600 text-sm">{err}</p>}
      {data && (
        <>
          <div className="overflow-x-auto rounded-xl border border-parchment-dark">
            <table className="w-full text-sm">
              <thead className="bg-parchment-dark text-xs text-gray-500 uppercase tracking-wider">
                <tr>
                  {['Email', 'Stripe Customer', 'Subscription ID', 'Period End'].map((h) => (
                    <th key={h} className="px-4 py-3 text-left font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-parchment-dark bg-white">
                {data.users.map((u) => (
                  <tr key={u.id} className="hover:bg-parchment/50 transition-colors">
                    <td className="px-4 py-3 font-medium text-ink max-w-[200px] truncate">{u.email}</td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {u.stripe_customer_id
                        ? <a href={`https://dashboard.stripe.com/customers/${u.stripe_customer_id}`} target="_blank" rel="noreferrer" className="text-ember hover:underline">{u.stripe_customer_id}</a>
                        : '—'}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-500 truncate max-w-[180px]">
                      {u.stripe_subscription_id || '—'}
                    </td>
                    <td className="px-4 py-3 text-gray-500">{fmtDate(u.current_period_end)}</td>
                  </tr>
                ))}
                {data.users.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-gray-400">No paid subscribers yet</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pages={data.pages} onChange={setPage} />
        </>
      )}
    </div>
  );
}

// ── Login form ────────────────────────────────────────────────────────────────

function LoginForm({ onLogin }: { onLogin: (token: string) => void }) {
  const [password, setPassword] = useState('');
  const [err, setErr]           = useState('');
  const [loading, setLoading]   = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr('');
    setLoading(true);
    try {
      const { token } = await adminLogin(password);
      localStorage.setItem(TOKEN_KEY, token);
      onLogin(token);
    } catch (ex: unknown) {
      setErr(ex instanceof Error ? ex.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-parchment flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 mb-2">
            <svg className="w-7 h-7 text-ember" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="16" y1="13" x2="8" y2="13"/>
              <line x1="16" y1="17" x2="8" y2="17"/>
            </svg>
            <span className="font-bold text-xl text-ink">ScanToText</span>
          </div>
          <p className="text-gray-500 text-sm">Admin dashboard — restricted access</p>
        </div>
        <form onSubmit={handleSubmit} className="bg-white border border-parchment-dark rounded-2xl p-8 shadow-sm space-y-5">
          <div>
            <label className="block text-sm font-medium text-ink mb-1.5">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoFocus
              required
              placeholder="Enter admin password"
              className="w-full border border-parchment-dark rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-ember/40 bg-white"
            />
          </div>
          {err && (
            <p className="text-red-600 text-sm bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {err}
            </p>
          )}
          <button
            type="submit"
            disabled={loading || !password}
            className="w-full bg-ember hover:bg-ember-dark text-white font-semibold rounded-lg px-4 py-2.5 text-sm transition-colors disabled:opacity-50"
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function AdminClient() {
  const [token, setToken]   = useState<string | null>(null);
  const [tab, setTab]       = useState<Tab>('overview');

  useEffect(() => {
    const stored = localStorage.getItem(TOKEN_KEY);
    if (stored) setToken(stored);
  }, []);

  function signOut() {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
  }

  function handleLogin(t: string) {
    setToken(t);
  }

  if (!token) return <LoginForm onLogin={handleLogin} />;

  const tabs: { id: Tab; label: string }[] = [
    { id: 'overview',  label: 'Overview' },
    { id: 'users',     label: 'Users' },
    { id: 'jobs',      label: 'Jobs' },
    { id: 'payments',  label: 'Payments' },
  ];

  return (
    <div className="min-h-screen bg-parchment">
      {/* Navbar */}
      <nav className="sticky top-0 z-50 bg-ink border-b border-ink-light">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <a href="/" className="flex items-center gap-2 font-bold text-white text-lg tracking-tight">
              <svg className="w-6 h-6 text-ember" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/>
                <line x1="16" y1="17" x2="8" y2="17"/>
              </svg>
              ScanToText
            </a>
            <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-ember text-white uppercase tracking-wider">
              Admin
            </span>
          </div>
          <button
            onClick={signOut}
            className="text-sm text-gray-400 hover:text-white transition-colors"
          >
            Sign out
          </button>
        </div>
      </nav>

      {/* Tab bar */}
      <div className="bg-white border-b border-parchment-dark sticky top-14 z-40">
        <div className="max-w-6xl mx-auto px-4 flex gap-1">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-5 py-3 text-sm font-semibold border-b-2 transition-colors ${
                tab === t.id
                  ? 'border-ember text-ember'
                  : 'border-transparent text-gray-500 hover:text-ink'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="max-w-6xl mx-auto px-4 py-8">
        {tab === 'overview'  && <OverviewTab  token={token} />}
        {tab === 'users'     && <UsersTab     token={token} />}
        {tab === 'jobs'      && <JobsTab      token={token} />}
        {tab === 'payments'  && <PaymentsTab  token={token} />}
      </div>
    </div>
  );
}
