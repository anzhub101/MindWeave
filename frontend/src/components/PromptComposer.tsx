import { LoaderCircle, Upload } from "lucide-react";

interface PromptComposerProps {
  prompt: string;
  onPromptChange: (value: string) => void;
  onSubmit: () => void;
  onFileSelect: (files: File[]) => void;
  deterministic: boolean;
  onDeterministicChange: (value: boolean) => void;
  autoApproveHumanReview: boolean;
  onAutoApproveHumanReviewChange: (value: boolean) => void;
  files: File[];
  isSubmitting: boolean;
  offlineDemo: boolean;
}

export function PromptComposer({
  prompt,
  onPromptChange,
  onSubmit,
  onFileSelect,
  deterministic,
  onDeterministicChange,
  autoApproveHumanReview,
  onAutoApproveHumanReviewChange,
  files,
  isSubmitting,
  offlineDemo,
}: PromptComposerProps) {
  return (
    <section className="max-h-[230px] overflow-y-auto rounded-[18px] bg-[var(--mw-panel)] px-4 py-3">
      <div className="mb-3 flex items-start justify-between gap-4">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.26em] text-[var(--mw-accent)]">
            Compose A Run
          </div>
          <div className="mt-1 font-serif text-[22px] leading-none text-[var(--mw-text)]">Prompt</div>
          <p className="mt-2 max-w-2xl text-[12px] leading-5 text-[var(--mw-subtle)]">
            Upload documents or run the bundled sample pack. The system synthesizes a reasoning
            program from the requirements reference, then records every state transition for export.
          </p>
        </div>

        {offlineDemo && (
          <div className="rounded-full border border-[var(--mw-border)] bg-[var(--mw-accent-soft)] px-3 py-2 text-[10px] uppercase tracking-[0.22em] text-[var(--mw-accent)]">
            Offline demo mode
          </div>
        )}
      </div>

      <textarea
        value={prompt}
        onChange={(event) => onPromptChange(event.target.value)}
        className="min-h-[82px] w-full resize-none rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3 text-[14px] leading-6 text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-border-strong)]"
      />

      <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-3">
          <div className="text-[13px] text-[var(--mw-subtle)]">
            {files.length > 0
              ? `${files.length} document${files.length === 1 ? "" : "s"} attached`
              : "No uploads attached. The bundled sample pack will be used."}
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-[var(--mw-muted)]">
            <label className="flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2">
              <input
                type="checkbox"
                checked={deterministic}
                onChange={(event) => onDeterministicChange(event.target.checked)}
                className="h-4 w-4 accent-[var(--mw-accent)]"
              />
              Deterministic mode
            </label>
            <label className="flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2">
              <input
                type="checkbox"
                checked={autoApproveHumanReview}
                onChange={(event) => onAutoApproveHumanReviewChange(event.target.checked)}
                className="h-4 w-4 accent-[var(--mw-accent)]"
              />
              Auto-approve review gates
            </label>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <label className="flex cursor-pointer items-center gap-2 rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-2.5 text-sm text-[var(--mw-text)] transition hover:border-[var(--mw-border-strong)]">
            <Upload size={15} strokeWidth={1.6} />
            Upload Documents
            <input
              type="file"
              multiple
              className="hidden"
              onChange={(event) => onFileSelect(Array.from(event.target.files ?? []))}
            />
          </label>

          <button
            type="button"
            onClick={onSubmit}
            disabled={isSubmitting}
            className="flex min-w-[120px] items-center justify-center gap-2 rounded-[18px] bg-[var(--mw-text)] px-5 py-2.5 text-sm font-medium text-[var(--mw-page)] transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmitting ? (
              <>
                <LoaderCircle size={15} className="animate-spin" strokeWidth={1.8} />
                Running
              </>
            ) : (
              "Submit"
            )}
          </button>
        </div>
      </div>
    </section>
  );
}
