import type { Metadata } from 'next';
import Footer from '@/components/Footer';

export const metadata: Metadata = { title: 'Privacy Policy — ScanToText' };

export default function PrivacyPage() {
  return (
    <>
      <nav className="sticky top-0 z-50 bg-white border-b border-gray-100 shadow-sm">
        <div className="max-w-5xl mx-auto px-4 h-14 flex items-center">
          <a href="/" className="flex items-center gap-2 font-bold text-gray-900">
            <svg className="w-6 h-6 text-indigo-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="16" y1="13" x2="8" y2="13"/>
              <line x1="16" y1="17" x2="8" y2="17"/>
            </svg>
            ScanToText
          </a>
        </div>
      </nav>
      <main className="max-w-3xl mx-auto px-6 py-12 pb-20">
        <h1 className="text-3xl font-extrabold text-gray-900 mb-2">Privacy Policy</h1>
        <p className="text-sm text-gray-500 mb-10">Last updated: February 2026</p>

        <Section title="1. Who we are">
          ScanToText (&quot;we&quot;, &quot;our&quot;, &quot;us&quot;) is an AI-powered document conversion service. This policy explains what personal data we collect, why, and your rights regarding it.
        </Section>
        <Section title="2. Data we collect">
          <ul className="list-disc pl-5 space-y-2">
            <li><strong>Email address</strong> — obtained via Google Sign-In when you create an account. Used solely for authentication and customer support.</li>
            <li><strong>Stripe billing data</strong> — name, card details, and billing address collected and stored by <a href="https://stripe.com/gb/privacy" target="_blank" rel="noopener" className="text-violet-600 underline">Stripe</a>. We receive only a customer ID and subscription status.</li>
            <li><strong>Uploaded documents</strong> — files you submit for OCR processing. Stored temporarily (maximum 24 hours) then permanently deleted by our automated cleanup process.</li>
            <li><strong>Usage data</strong> — page counts processed per billing period, stored for quota enforcement.</li>
            <li><strong>Server logs</strong> — standard access logs retained for up to 30 days for security and debugging.</li>
          </ul>
        </Section>
        <Section title="3. How we use your data">
          <ul className="list-disc pl-5 space-y-2">
            <li>Provide and improve the OCR conversion service.</li>
            <li>Manage subscriptions and enforce page quotas.</li>
            <li>Comply with legal obligations (e.g. fraud prevention, tax records).</li>
          </ul>
          <p className="mt-3">We do <strong>not</strong> sell, share, or use your documents or email address for marketing or third-party advertising.</p>
        </Section>
        <Section title="4. Third-party processors">
          <p>Your documents are processed by:</p>
          <ul className="list-disc pl-5 space-y-2 mt-2">
            <li><strong>Azure Document Intelligence</strong> (Microsoft) — OCR and layout analysis.</li>
            <li><strong>Google Gemini</strong> — semantic HTML output.</li>
            <li><strong>Mistral AI</strong> — Markdown and image extraction.</li>
          </ul>
          <p className="mt-3">Each processor handles data under their own privacy policies and data processing agreements compliant with GDPR.</p>
        </Section>
        <Section title="5. Data retention">
          Uploaded documents are deleted within 24 hours. Account data (email, subscription status, usage counts) is retained while your account is active and for 12 months after closure.
        </Section>
        <Section title="6. Your rights">
          Under UK/EU GDPR you have the right to access, correct, or delete your personal data. Contact us at the email in the footer to exercise these rights.
        </Section>
        <Section title="7. Cookies">
          We do not use tracking or advertising cookies. A session token is stored in localStorage solely to maintain your login state.
        </Section>
        <Section title="8. Changes">
          We may update this policy. Continued use of the Service after changes constitutes acceptance.
        </Section>
      </main>
      <Footer />
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="text-base font-bold text-gray-900 mb-3">{title}</h2>
      <div className="text-sm text-gray-700 leading-7">{children}</div>
    </section>
  );
}
