"use client";

import { useEffect, useState } from "react";
import type { DocumentInfo } from "@/lib/types";
import DocumentCard from "./DocumentCard";
import { Loader2 } from "lucide-react";

export default function DocumentSelector() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/documents")
      .then((res) => res.json())
      .then((data) => {
        setDocuments(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-20 text-center text-[var(--destructive)]">
        Failed to load documents: {error}
      </div>
    );
  }

  if (documents.length === 0) {
    return (
      <div className="py-20 text-center text-[var(--muted-foreground)]">
        No documents found. Make sure PDFs and output files are in the correct directories.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
      {documents.map((doc) => (
        <DocumentCard key={doc.docId} doc={doc} />
      ))}
    </div>
  );
}
