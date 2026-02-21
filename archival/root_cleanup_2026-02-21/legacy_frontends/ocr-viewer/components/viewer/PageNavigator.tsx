"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState, useEffect } from "react";

interface PageNavigatorProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export default function PageNavigator({
  currentPage,
  totalPages,
  onPageChange,
}: PageNavigatorProps) {
  const [inputValue, setInputValue] = useState(String(currentPage));

  useEffect(() => {
    setInputValue(String(currentPage));
  }, [currentPage]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const page = parseInt(inputValue, 10);
    if (!isNaN(page) && page >= 1 && page <= totalPages) {
      onPageChange(page);
    } else {
      setInputValue(String(currentPage));
    }
  }

  return (
    <div className="flex items-center gap-1">
      <button
        onClick={() => onPageChange(Math.max(1, currentPage - 1))}
        disabled={currentPage <= 1}
        className="rounded p-1 hover:bg-[var(--accent)] disabled:opacity-30 text-[var(--muted-foreground)]"
        title="Previous page"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
      <form onSubmit={handleSubmit} className="flex items-center gap-1">
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          className="w-10 rounded border border-[var(--border)] bg-[var(--background)] px-1 py-0.5 text-center text-xs tabular-nums"
          onBlur={handleSubmit}
        />
        <span className="text-xs text-[var(--muted-foreground)]">/ {totalPages}</span>
      </form>
      <button
        onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
        disabled={currentPage >= totalPages}
        className="rounded p-1 hover:bg-[var(--accent)] disabled:opacity-30 text-[var(--muted-foreground)]"
        title="Next page"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}
