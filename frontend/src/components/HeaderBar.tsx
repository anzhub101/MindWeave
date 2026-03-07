import { ChevronDown, Clock3, Search, UserRound } from "lucide-react";

interface HeaderBarProps {
  pageTitle: string;
  pageEyebrow: string;
  taskLabel: string;
  historyCount: number;
}

export function HeaderBar({ pageTitle, pageEyebrow, taskLabel, historyCount }: HeaderBarProps) {
  return (
    <header className="flex items-center justify-between border-b border-[var(--mw-border)] px-5 py-4 lg:px-6">
      <div className="flex min-w-0 items-center gap-6">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.26em] text-[var(--mw-accent)]">
            {pageEyebrow}
          </div>
          <div className="mt-1 font-serif text-[32px] leading-none tracking-[-0.035em] text-[var(--mw-text)]">
            {pageTitle}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2.5">
        <button
          type="button"
          className="hidden h-11 items-center gap-3 rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 text-[var(--mw-text)] lg:flex"
        >
          <Search size={16} strokeWidth={1.6} />
          <span className="text-sm">Reasoning graph</span>
          <ChevronDown size={14} strokeWidth={1.6} />
        </button>

        <button
          type="button"
          className="flex h-11 items-center gap-2 rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-accent-soft)] px-4 text-[var(--mw-accent)]"
        >
          <Clock3 size={16} strokeWidth={1.6} />
          <span className="text-sm">MVP Environment</span>
        </button>

        <div className="hidden rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-3 text-right xl:block">
          <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--mw-subtle)]">Current Run</div>
          <div className="mt-1 max-w-[220px] truncate text-sm text-[var(--mw-text)]">{taskLabel}</div>
        </div>

        <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-3 text-right">
          <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--mw-subtle)]">History</div>
          <div className="text-sm text-[var(--mw-text)]">{historyCount} runs</div>
        </div>

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
