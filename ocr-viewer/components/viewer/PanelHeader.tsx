"use client";

export default function PanelHeader({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex h-10 items-center justify-between border-b border-[var(--border)] bg-[var(--muted)] px-3">
      <span className="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
        {title}
      </span>
      <div className="flex items-center gap-1">{children}</div>
    </div>
  );
}
