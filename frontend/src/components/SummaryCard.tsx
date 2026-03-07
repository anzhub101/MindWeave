import { useState } from "react";
import { ChevronDown, ChevronUp, Download, ShieldCheck } from "lucide-react";

interface SummaryCardProps {
  status: "queued" | "running" | "paused" | "completed" | "failed";
  summary: {
    headline: string;
    verdict: string;
    key_points: string[];
    metrics: {
      label: string;
      value: string;
    }[];
  } | null;
  pendingReviewNodeId: string | null;
  onApproveReview?: () => void;
  onRejectReview?: () => void;
  onExport: () => void;
}

export function SummaryCard({
  status,
  summary,
  pendingReviewNodeId,
  onApproveReview,
  onRejectReview,
  onExport,
}: SummaryCardProps) {
  const [isOpen, setIsOpen] = useState(false);

  if (!summary && status !== "paused") {
    return null;
  }

  return (
    <div className="max-h-[260px] overflow-hidden rounded-[18px] bg-[var(--mw-panel)] px-4 py-3">
      <button
        type="button"
        onClick={() => setIsOpen((current) => !current)}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.26em] text-[var(--mw-accent)]">
            Run Summary
          </div>
          <div className="mt-1 font-serif text-[20px] leading-none text-[var(--mw-text)]">
            {summary?.headline ?? "Human Review Required"}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full border border-[var(--mw-border)] bg-[var(--mw-accent-soft)] px-3 py-1.5 text-[10px] uppercase tracking-[0.22em] text-[var(--mw-accent)]">
            {summary?.verdict ?? "Paused"}
          </span>
          {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </div>
      </button>

      {isOpen && summary && (
        <div className="mt-4 grid max-h-[120px] gap-3 overflow-y-auto pr-1 text-sm text-[var(--mw-muted)] md:grid-cols-2">
          {summary.metrics.slice(0, 4).map((metric) => (
            <div key={metric.label} className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
              <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--mw-subtle)]">
                {metric.label}
              </div>
              <div className="mt-2 font-serif text-[22px] leading-none text-[var(--mw-text)]">{metric.value}</div>
            </div>
          ))}
        </div>
      )}

      {isOpen && summary && (
        <div className="mt-3 max-h-[96px] overflow-y-auto rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3 pr-1">
          <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--mw-subtle)]">Highlights</div>
          <div className="mt-2 space-y-2 text-sm text-[var(--mw-muted)]">
            {summary.key_points.map((point) => (
              <div key={point}>{point}</div>
            ))}
          </div>
        </div>
      )}

      {isOpen && status === "paused" && pendingReviewNodeId && (
        <div className="mt-3 rounded-2xl border border-[var(--mw-border)] bg-[var(--mw-accent-soft)] p-3">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-accent)]">Human Review</div>
          <div className="mt-2 text-sm leading-6 text-[var(--mw-text)]">
            Execution is paused waiting for reviewer input on{" "}
            <span className="font-mono">{pendingReviewNodeId}</span>.
          </div>
          <div className="mt-3 flex gap-3">
            <button
              type="button"
              onClick={onApproveReview}
              className="rounded-2xl bg-[var(--mw-text)] px-4 py-2 text-sm text-[var(--mw-page)]"
            >
              Approve
            </button>
            <button
              type="button"
              onClick={onRejectReview}
              className="rounded-2xl border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-2 text-sm text-[var(--mw-text)]"
            >
              Reject
            </button>
          </div>
        </div>
      )}

      <div className="mt-5 flex items-center justify-between">
        <div className="flex items-center gap-2 text-[var(--mw-accent)]">
          <ShieldCheck size={16} strokeWidth={1.6} />
          <span className="text-sm">
            {status === "completed" ? "Verifiable audit package ready" : "Traceable reasoning state available"}
          </span>
        </div>
        <button
          type="button"
          onClick={onExport}
          className="flex items-center gap-2 rounded-2xl border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-2 text-sm text-[var(--mw-text)] transition hover:border-[var(--mw-border-strong)]"
        >
          <Download size={15} strokeWidth={1.6} />
          Export
        </button>
      </div>
    </div>
  );
}
