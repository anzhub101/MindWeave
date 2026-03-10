import { Download, ShieldCheck, X } from "lucide-react";

interface SummaryCardProps {
  status: "queued" | "running" | "paused" | "completed" | "failed";
  determinismMode?: string;
  controlLevel?: string;
  modelVersion?: string;
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
  onDismiss?: () => void;
  onExport: () => void;
}

export function SummaryCard({
  status,
  determinismMode,
  controlLevel,
  modelVersion,
  summary,
  pendingReviewNodeId,
  onApproveReview,
  onRejectReview,
  onDismiss,
  onExport,
}: SummaryCardProps) {
  if (!summary && status !== "paused") {
    return null;
  }

  return (
    <div className="soft-panel flex h-full flex-col overflow-hidden rounded-[28px] border border-[var(--mw-border)] shadow-[0_24px_80px_rgba(0,0,0,0.24)]">
      <div className="flex items-start justify-between gap-4 border-b border-[var(--mw-border)] px-6 py-5 lg:px-8 lg:py-6">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.26em] text-[var(--mw-accent)]">
            Run Summary
          </div>
          <div className="mt-2 font-sans text-[30px] font-semibold leading-[0.96] tracking-[-0.03em] text-[var(--mw-text)] lg:text-[38px]">
            {summary?.headline ?? "Human Review Required"}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="rounded-full border border-[var(--mw-border)] bg-[var(--mw-accent-soft)] px-3 py-1.5 text-[10px] uppercase tracking-[0.22em] text-[var(--mw-accent)]">
            {summary?.verdict ?? "Paused"}
          </span>
          <button
            type="button"
            onClick={onDismiss}
            className="flex h-10 w-10 items-center justify-center rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] text-[var(--mw-subtle)] transition hover:border-[var(--mw-border-strong)] hover:text-[var(--mw-text)]"
            aria-label="Close run summary"
          >
            <X size={16} strokeWidth={1.7} />
          </button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 gap-5 overflow-y-auto px-6 py-5 lg:grid-cols-[1.2fr_0.8fr] lg:px-8 lg:py-6">
        <div className="space-y-5">
          {summary ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {summary.metrics.slice(0, 4).map((metric) => (
                <div
                  key={metric.label}
                  className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4"
                >
                  <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--mw-subtle)]">
                    {metric.label}
                  </div>
                  <div className="mt-3 font-sans text-[28px] font-semibold leading-none text-[var(--mw-text)]">
                    {metric.value}
                  </div>
                </div>
              ))}
            </div>
          ) : null}

          <div className="rounded-[20px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4 lg:p-5">
            <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--mw-subtle)]">Highlights</div>
            <div className="mt-3 space-y-3 text-[15px] leading-7 text-[var(--mw-muted)]">
              {(summary?.key_points ?? ["Execution is paused awaiting reviewer input."]).map((point) => (
                <div key={point}>{point}</div>
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-5">
          {status === "paused" && pendingReviewNodeId ? (
            <div className="rounded-[20px] border border-[var(--mw-border)] bg-[var(--mw-accent-soft)] p-4 lg:p-5">
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-accent)]">
                Human Review
              </div>
              <div className="mt-3 text-[15px] leading-7 text-[var(--mw-text)]">
                Execution is paused waiting for reviewer input on{" "}
                <span className="font-mono text-[14px]">{pendingReviewNodeId}</span>.
              </div>
              <div className="mt-4 flex gap-3">
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
          ) : null}

          <div className="rounded-[20px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4 lg:p-5">
            <div className="flex items-start gap-3">
              <ShieldCheck size={18} strokeWidth={1.6} className="mt-0.5 text-[var(--mw-accent)]" />
              <div>
                <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--mw-subtle)]">Audit State</div>
                <div className="mt-2 text-[15px] leading-7 text-[var(--mw-muted)]">
                  {status === "completed"
                    ? "Verifiable audit package ready for export."
                    : "Traceable reasoning state is available for review and export."}
                </div>
                <div className="mt-3 text-[12px] uppercase tracking-[0.14em] text-[var(--mw-subtle)]">
                  {determinismMode ? `${determinismMode.replace(/_/g, " ")}` : "runtime"} · {controlLevel ? controlLevel.replace(/_/g, " ") : "control"} · {modelVersion || "model unavailable"}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-end border-t border-[var(--mw-border)] px-6 py-4 lg:px-8">
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
