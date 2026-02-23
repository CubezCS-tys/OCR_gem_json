'use client';

import { useCallback, useEffect, useState } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';

import Navbar from '@/components/Navbar';
import UploadZone from '@/components/UploadZone';
import FileSection from '@/components/FileSection';
import ProcessingSection from '@/components/ProcessingSection';
import ResultSection from '@/components/ResultSection';
import ErrorSection from '@/components/ErrorSection';
import LoginModal from '@/components/LoginModal';
import PricingSection from '@/components/PricingSection';
import Footer from '@/components/Footer';

import {
  fetchConfig, uploadFile, processFree, processPro,
  fetchAccount, activateTrial, startSubscription, getManagePortal,
  AppConfig, AccountInfo, ProcessResult,
} from '@/lib/api';
import { getToken, getEmail, storeAuth, clearAuth } from '@/lib/auth';

type View = 'upload' | 'file' | 'processing' | 'result' | 'error';

export default function HomeClient() {
  const searchParams = useSearchParams();
  const router = useRouter();

  // ── Auth ──────────────────────────────────────────────────────────────────
  const [token, setToken]     = useState('');
  const [, setEmail]          = useState('');
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [loginOpen, setLoginOpen]   = useState(false);
  const [authError, setAuthError]   = useState<string | undefined>();

  // ── Config ────────────────────────────────────────────────────────────────
  const [config, setConfig] = useState<AppConfig | null>(null);

  // ── Job state ─────────────────────────────────────────────────────────────
  const [view, setView]           = useState<View>('upload');
  const [uploading, setUploading] = useState(false);
  const [jobId, setJobId]         = useState<string | null>(null);
  const [filename, setFilename]   = useState('');
  const [fileSizeMb, setFileSizeMb] = useState('');
  const [pageCount, setPageCount]   = useState(1);
  const [result, setResult]         = useState<ProcessResult | null>(null);
  const [errorMsg, setErrorMsg]     = useState('');
  const [procTitle, setProcTitle]   = useState('');
  const [procMsg, setProcMsg]       = useState('');
  const [procDuration, setProcDuration] = useState(25000);

  // ── Helpers ───────────────────────────────────────────────────────────────
  const refreshAccount = useCallback(async (tok?: string) => {
    const t = tok ?? token;
    if (!t) { setAccount(null); return; }
    try {
      const acc = await fetchAccount(t);
      setAccount(acc);
    } catch (e: unknown) {
      if ((e as Error).message === 'unauthorized') {
        clearAuth();
        setToken('');
        setAccount(null);
      }
    }
  }, [token]);

  // ── Init ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    fetchConfig().then(setConfig).catch(() => {});

    const storedToken = getToken();
    const storedEmail = getEmail();
    if (storedToken) {
      setToken(storedToken);
      setEmail(storedEmail);
      refreshAccount(storedToken);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Handle Google OAuth redirect
  useEffect(() => {
    const tok = searchParams.get('token');
    const em  = searchParams.get('email');
    const err = searchParams.get('auth_error');

    if (tok && em) {
      storeAuth(tok, em);
      setToken(tok);
      setEmail(em);
      router.replace('/');
      fetchAccount(tok).then(async (acc) => {
        setAccount(acc);
        if (!acc.is_active) {
          await activateTrial(tok).catch(() => {});
          const updated = await fetchAccount(tok).catch(() => acc);
          setAccount(updated);
        }
      }).catch(() => {});
    } else if (err) {
      const msgs: Record<string, string> = {
        state_mismatch: 'Login failed (security check). Please try again.',
        google_failed:  'Google sign-in failed. Please try again.',
        access_denied:  'Access was denied. Please try again.',
      };
      setAuthError(msgs[err] ?? 'Sign-in failed. Please try again.');
      setLoginOpen(true);
      router.replace('/');
    }
  }, [searchParams, router]);

  // ── File selected ─────────────────────────────────────────────────────────
  async function handleFile(file: File) {
    const maxMb = config?.max_file_size_mb ?? 50;
    if (file.size > maxMb * 1024 * 1024) {
      setErrorMsg(`File too large. Max ${maxMb} MB.`);
      setView('error');
      return;
    }

    setFilename(file.name);
    setFileSizeMb((file.size / 1024 / 1024).toFixed(1));
    setJobId(null);
    setUploading(true);
    setView('file');

    try {
      const data = await uploadFile(file);
      setJobId(data.job_id);
      setPageCount(data.page_count || 1);
    } catch (e: unknown) {
      setErrorMsg((e as Error).message);
      setView('error');
    } finally {
      setUploading(false);
    }
  }

  // ── Reset ─────────────────────────────────────────────────────────────────
  function reset() {
    setJobId(null);
    setPageCount(1);
    setResult(null);
    setErrorMsg('');
    setView('upload');
  }

  // ── Process ───────────────────────────────────────────────────────────────
  async function handleConvert(tier: 'free' | 'pro', formats?: string) {
    if (!jobId) return;

    if (tier === 'free') {
      setProcTitle('Converting — Searchable PDF');
      setProcMsg('Running OCR engine...');
      setProcDuration(25000);
    } else {
      setProcTitle('Converting — All Formats (Pro)');
      setProcMsg('Running 3 AI engines in parallel...');
      setProcDuration(70000);
    }
    setView('processing');

    try {
      const data =
        tier === 'free'
          ? await processFree(jobId)
          : await processPro(jobId, formats ?? '', token);
      setResult(data);
      if (tier === 'pro') await refreshAccount();
      setView('result');
    } catch (e: unknown) {
      setErrorMsg((e as Error).message);
      setView('error');
    }
  }

  // ── Subscription ──────────────────────────────────────────────────────────
  async function handleSubscribe() {
    if (!token) { setLoginOpen(true); return; }
    try {
      const data = await startSubscription(token);
      if (data.url) window.location.href = data.url;
      else if (data.demo_mode) await refreshAccount();
    } catch (e: unknown) {
      setErrorMsg((e as Error).message);
      setView('error');
    }
  }

  async function handleManage() {
    if (config?.demo_mode) { alert('Demo mode — management simulated.'); return; }
    try {
      const data = await getManagePortal(token);
      if (data.portal_url) window.location.href = data.portal_url;
    } catch (e: unknown) {
      setErrorMsg((e as Error).message);
      setView('error');
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────
  const maxMb = config?.max_file_size_mb ?? 50;

  return (
    <>
      <Navbar
        config={config}
        account={account}
        onAuthClick={() => setLoginOpen(true)}
        onManageClick={handleManage}
      />

      {loginOpen && (
        <LoginModal
          authError={authError}
          onClose={() => { setLoginOpen(false); setAuthError(undefined); }}
        />
      )}

      <main>
        {/* Hero */}
        <section className="hero-grid py-20 relative overflow-hidden">
          <div className="max-w-5xl mx-auto px-4 text-center relative">
            <span className="inline-block px-3 py-1 rounded-full bg-ember/20 text-ember border border-ember/30 text-xs font-semibold mb-5 tracking-widest uppercase">
              OCR + AI Document Conversion
            </span>
            <h1 className="text-4xl md:text-5xl font-bold text-white leading-tight mb-5">
              Every format you need,<br className="hidden md:block"/> from one upload
            </h1>
            <p className="text-lg text-gray-400 max-w-2xl mx-auto">
              Searchable PDF, pixel-perfect HTML, semantic HTML, markdown — powered by Azure, Gemini, and Mistral AI. Free tier included.
            </p>
          </div>
        </section>

        {/* App widget */}
        <div className="bg-parchment">
          <div className="max-w-5xl mx-auto px-4 py-10 space-y-4">
            {view === 'upload' && (
              <UploadZone maxMb={maxMb} onFile={handleFile} />
            )}
            {view === 'file' && (
              <FileSection
                filename={filename}
                fileSizeMb={fileSizeMb}
                pageCount={pageCount}
                uploading={uploading}
                config={config}
                account={account}
                onRemove={reset}
                onConvert={handleConvert}
                onNeedAuth={() => setLoginOpen(true)}
              />
            )}
            {view === 'processing' && (
              <ProcessingSection
                title={procTitle}
                message={procMsg}
                durationMs={procDuration}
              />
            )}
            {view === 'result' && result && (
              <ResultSection
                jobId={result.job_id}
                filename={result.filename}
                formats={result.formats ?? result.formats_produced}
                isPro={account?.is_active ?? false}
                onNew={reset}
              />
            )}
            {view === 'error' && (
              <ErrorSection message={errorMsg} onRetry={reset} />
            )}
          </div>
        </div>

        <PricingSection
          priceDisplay={config?.plan_price_display ?? '£20'}
          onSubscribe={handleSubscribe}
        />

        {/* How It Works */}
        <section className="py-20 bg-parchment">
          <div className="max-w-5xl mx-auto px-4">
            <h2 className="text-3xl font-bold text-center text-ink mb-2">How It Works</h2>
            <p className="text-center text-gray-500 mb-14">Three steps to any document format you need.</p>
            <div className="grid md:grid-cols-3 gap-8">
              {[
                { n: '01', title: 'Upload', desc: 'Drop in any scanned PDF or image — invoices, books, contracts, manuscripts.' },
                { n: '02', title: 'Choose', desc: 'Free searchable PDF, or Pro for all formats — HTML, semantic, markdown, figures.' },
                { n: '03', title: 'Download', desc: 'Get a ZIP with every format, or just the searchable PDF. Ready in under a minute.' },
              ].map((s) => (
                <div key={s.n} className="bg-white rounded-2xl p-8 border border-parchment-dark">
                  <div className="w-10 h-10 bg-ember/10 rounded-xl flex items-center justify-center mb-5">
                    <span className="text-sm font-bold text-ember">{s.n}</span>
                  </div>
                  <h4 className="font-semibold text-ink mb-2 text-lg">{s.title}</h4>
                  <p className="text-sm text-gray-500 leading-relaxed">{s.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>

      <Footer />
    </>
  );
}
