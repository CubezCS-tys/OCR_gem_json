import { Suspense } from 'react';
import DashboardClient from '@/components/DashboardClient';

export const metadata = { title: 'Dashboard — ScanToText' };

export default function DashboardPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-gray-400">Loading…</div>
      </div>
    }>
      <DashboardClient />
    </Suspense>
  );
}
