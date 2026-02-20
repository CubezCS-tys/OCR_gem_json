import AppHeader from "@/components/layout/AppHeader";
import DocumentSelector from "@/components/viewer/DocumentSelector";

export default function HomePage() {
  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold">Documents</h1>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            Select a document to view the original PDF alongside the OCR output.
          </p>
        </div>
        <DocumentSelector />
      </main>
    </div>
  );
}
