import { Suspense } from 'react';
import AdminClient from '@/components/AdminClient';

export const metadata = { title: 'Admin — ScanToText' };

export default function AdminPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-parchment">
          <div className="text-gray-400">Loading…</div>
        </div>
      }
    >
      <AdminClient />
    </Suspense>
  );
}
