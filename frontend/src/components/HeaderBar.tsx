import type { ReactNode } from "react";
import { FileChartColumn, UserRound } from "lucide-react";

interface HeaderBarProps {
  pageTitle: string;
  pageEyebrow: string;
  summaryOpen: boolean;
  onToggleSummary: () => void;
  contextActions?: ReactNode;
}

export function HeaderBar({ pageTitle, pageEyebrow, summaryOpen, onToggleSummary, contextActions }: HeaderBarProps) {
  return (
    <header className="flex items-center justify-between border-b border-[var(--mw-border)] px-5 py-4 lg:px-6">
      <div className="flex min-w-0 items-center gap-6">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.26em] text-[var(--mw-accent)]">
            {pageEyebrow}
          </div>
          <div className="mt-1 font-sans text-[32px] font-semibold leading-none tracking-[-0.035em] text-[var(--mw-text)]">
            {pageTitle}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2.5">
        {contextActions}
        <button
          type="button"
          onClick={onToggleSummary}
          className="flex h-11 items-center gap-3 rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 text-[var(--mw-text)]"
        >
          <FileChartColumn size={16} strokeWidth={1.6} />
          <span className="text-sm">{summaryOpen ? "Hide Run Summary" : "Run Summary"}</span>
        </button>

        <button
          type="button"
          className="flex h-11 w-11 items-center justify-center rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] text-[var(--mw-text)]"
        >
          <UserRound size={18} strokeWidth={1.6} />
        </button>
      </div>
    </header>
  );
}
