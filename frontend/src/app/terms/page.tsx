import type { Metadata } from 'next';
import Footer from '@/components/Footer';

export const metadata: Metadata = { title: 'Terms of Service — ScanToText' };

export default function TermsPage() {
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
        <h1 className="text-3xl font-extrabold text-gray-900 mb-2">Terms of Service</h1>
        <p className="text-sm text-gray-500 mb-10">Last updated: February 2026</p>

        <Section title="1. Acceptance">
          By accessing or using ScanToText (&quot;the Service&quot;), you agree to be bound by these Terms. If you do not agree, do not use the Service.
        </Section>
        <Section title="2. Description of service">
          ScanToText converts scanned documents and images into searchable PDFs, HTML, and Markdown using AI OCR engines. A free tier and a paid Pro subscription are available.
        </Section>
        <Section title="3. Accounts &amp; authentication">
          You sign in using a Google account. You are responsible for the security of your account and for all activity that occurs under it. Notify us immediately of any unauthorised use.
        </Section>
        <Section title="4. Subscriptions &amp; billing">
          <ul className="list-disc pl-5 space-y-2">
            <li>Pro subscriptions are billed monthly via Stripe. Prices are shown on the pricing page.</li>
            <li>Subscriptions auto-renew until cancelled. You may cancel at any time via the customer portal; cancellation takes effect at the end of the current billing period.</li>
            <li>Page quotas reset on your monthly renewal date. Unused pages do not carry over.</li>
            <li>No refunds are issued for partial months except where required by applicable law (e.g. UK Consumer Contracts Regulations).</li>
          </ul>
        </Section>
        <Section title="5. Acceptable use">
          <p>You agree not to:</p>
          <ul className="list-disc pl-5 space-y-2 mt-2">
            <li>Upload documents you do not own or are not authorised to process.</li>
            <li>Use the Service to process content that is unlawful, infringing, or violates third-party rights.</li>
            <li>Attempt to circumvent rate limits, quotas, or payment mechanisms.</li>
            <li>Reverse-engineer, scrape, or abuse the API in ways that harm service stability.</li>
          </ul>
        </Section>
        <Section title="6. Intellectual property">
          The Service and its original content, features, and functionality are owned by ScanToText and protected by applicable intellectual property laws. Converted output files are owned by you.
        </Section>
        <Section title="7. Disclaimer of warranties">
          The Service is provided &quot;as is&quot; without warranties of any kind. OCR accuracy may vary depending on document quality and language.
        </Section>
        <Section title="8. Limitation of liability">
          To the fullest extent permitted by law, ScanToText shall not be liable for any indirect, incidental, special, or consequential damages arising out of your use of the Service.
        </Section>
        <Section title="9. Governing law">
          These Terms are governed by the laws of England and Wales. Any disputes shall be subject to the exclusive jurisdiction of the courts of England and Wales.
        </Section>
        <Section title="10. Changes">
          We reserve the right to modify these Terms at any time. Continued use of the Service after changes constitutes acceptance.
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
