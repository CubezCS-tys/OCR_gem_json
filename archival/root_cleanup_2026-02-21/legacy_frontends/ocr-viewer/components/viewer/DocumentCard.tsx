"use client";

import Link from "next/link";
import { FileText, FileImage, FileJson } from "lucide-react";
import type { DocumentInfo } from "@/lib/types";

function Badge({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
        active
          ? "bg-emerald-100 text-emerald-700"
          : "bg-gray-100 text-gray-400"
      }`}
    >
      {children}
    </span>
  );
}

export default function DocumentCard({ doc }: { doc: DocumentInfo }) {
  const viewable = doc.hasPdf && doc.hasHtml;

  return (
    <Link
      href={viewable ? `/viewer/${doc.docId}` : "#"}
      className={`group block rounded-lg border border-[var(--border)] p-4 transition-all ${
        viewable
          ? "hover:border-[var(--primary)] hover:shadow-md cursor-pointer"
          : "opacity-50 cursor-not-allowed"
      }`}
      onClick={(e) => !viewable && e.preventDefault()}
    >
      <div className="mb-3 font-mono text-sm font-semibold">{doc.docId}</div>
      <div className="flex flex-wrap gap-1.5">
        <Badge active={doc.hasPdf}>
          <FileImage className="h-3 w-3" /> PDF
        </Badge>
        <Badge active={doc.hasHtml}>
          <FileText className="h-3 w-3" /> HTML
        </Badge>
        <Badge active={doc.hasJson}>
          <FileJson className="h-3 w-3" /> JSON
        </Badge>
      </div>
    </Link>
  );
}
