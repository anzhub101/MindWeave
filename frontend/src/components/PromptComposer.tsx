import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { LoaderCircle, Upload, ChevronDown, ChevronUp, X } from "lucide-react";

interface PromptComposerProps {
  prompt: string;
  onPromptChange: (value: string) => void;
  sourceUrls: string;
  onSourceUrlsChange: (value: string) => void;
  onSubmit: () => void;
  onFileSelect: (files: File[]) => void;
  onRemoveFile: (index: number) => void;
  determinismMode: "non_deterministic" | "best_effort_deterministic" | "strict_deterministic";
  onDeterminismModeChange: (value: "non_deterministic" | "best_effort_deterministic" | "strict_deterministic") => void;
  controlLevel: "exploratory" | "operational" | "regulated" | "strict_audit";
  onControlLevelChange: (value: "exploratory" | "operational" | "regulated" | "strict_audit") => void;
  autoApproveHumanReview: boolean;
  onAutoApproveHumanReviewChange: (value: boolean) => void;
  files: File[];
  isSubmitting: boolean;
  offlineDemo: boolean;
  countdownTime?: number | null;
  isNodeSelected?: boolean; // New prop
}

export function PromptComposer({
  prompt,
  onPromptChange,
  sourceUrls,
  onSourceUrlsChange,
  onSubmit,
  onFileSelect,
  onRemoveFile,
  determinismMode,
  onDeterminismModeChange,
  controlLevel,
  onControlLevelChange,
  autoApproveHumanReview,
  onAutoApproveHumanReviewChange,
  files,
  isSubmitting,
  offlineDemo,
  countdownTime = null,
  isNodeSelected = false,
}: PromptComposerProps) {
  // Local state to manage expansion
  const [isExpanded, setIsExpanded] = useState(!isNodeSelected);

  // Auto-collapse when a node is selected, auto-expand when deselected
  useEffect(() => {
    setIsExpanded(!isNodeSelected);
  }, [isNodeSelected]);

  return (
    <section className="overflow-y-auto rounded-[18px] bg-[var(--mw-panel)] px-4 py-3">
      <button
        type="button"
        onClick={() => setIsExpanded((prev) => !prev)}
        className="flex w-full items-start justify-between gap-4 text-left outline-none"
      >
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.26em] text-[var(--mw-accent)]">
            Compose A Run
          </div>
          <div className="mt-1 flex items-center gap-2 font-sans text-[22px] font-semibold leading-none text-[var(--mw-text)]">
            Prompt
            {isExpanded ? (
              <ChevronUp size={16} className="text-[var(--mw-subtle)] transition hover:text-[var(--mw-text)]" />
            ) : (
              <ChevronDown size={16} className="text-[var(--mw-subtle)] transition hover:text-[var(--mw-text)]" />
            )}
          </div>
        </div>
      </button>

      <AnimatePresence initial={false}>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0, marginTop: 0 }}
            animate={{ height: "auto", opacity: 1, marginTop: 12 }}
            exit={{ height: 0, opacity: 0, marginTop: 0 }}
            transition={{ duration: 0.28, ease: [0.2, 1, 0.2, 1] }} // Smooth easing to match the rest of your UI
            className="overflow-hidden"
          >
            <textarea
              value={prompt}
              onChange={(event) => onPromptChange(event.target.value)}
              className="min-h-[82px] w-full resize-none rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3 text-[14px] leading-6 text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-border-strong)]"
            />

            <textarea
              value={sourceUrls}
              onChange={(event) => onSourceUrlsChange(event.target.value)}
              placeholder={"Optional source URLs, one per line.\nhttps://example.com/report\nhttps://example.com/filing.pdf"}
              className="mt-3 min-h-[82px] w-full resize-none rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3 font-mono text-[13px] leading-6 text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-border-strong)]"
            />

            <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
              <div className="space-y-3">
                <div className="text-[13px] text-[var(--mw-subtle)]">
                  {files.length > 0 || sourceUrls.trim()
                    ? `${files.length} upload${files.length === 1 ? "" : "s"} attached${sourceUrls.trim() ? ` · ${sourceUrls.split(/\n+/).filter(Boolean).length} source URL${sourceUrls.split(/\n+/).filter(Boolean).length === 1 ? "" : "s"}` : ""}`
                    : "No uploads attached. If web fallback is configured, the runtime will anchor to live web evidence."}
                </div>
                {files.length ? (
                  <div className="flex flex-wrap gap-2">
                    {files.map((file, index) => (
                      <div
                        key={`${file.name}-${index}`}
                        className="inline-flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] text-[var(--mw-text)]"
                      >
                        <span className="max-w-[16rem] truncate">{file.name}</span>
                        <button
                          type="button"
                          onClick={() => onRemoveFile(index)}
                          className="inline-flex h-5 w-5 items-center justify-center rounded-full text-[var(--mw-subtle)] transition hover:bg-[var(--mw-node)] hover:text-[var(--mw-text)]"
                          aria-label={`Remove ${file.name}`}
                        >
                          <X size={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="flex flex-wrap gap-3 text-xs text-[var(--mw-muted)]">
                  <label className="flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2">
                    <span>Mode</span>
                    <select
                      value={determinismMode}
                      onChange={(event) => onDeterminismModeChange(event.target.value as PromptComposerProps["determinismMode"])}
                      className="bg-transparent text-[var(--mw-text)] outline-none"
                    >
                      <option value="non_deterministic">Non-deterministic</option>
                      <option value="best_effort_deterministic">Best-effort deterministic</option>
                      <option value="strict_deterministic">Strict deterministic</option>
                    </select>
                  </label>
                  <label className="flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2">
                    <span>Control</span>
                    <select
                      value={controlLevel}
                      onChange={(event) => onControlLevelChange(event.target.value as PromptComposerProps["controlLevel"])}
                      className="bg-transparent text-[var(--mw-text)] outline-none"
                    >
                      <option value="exploratory">Exploratory</option>
                      <option value="operational">Operational</option>
                      <option value="regulated">Regulated</option>
                      <option value="strict_audit">Strict audit</option>
                    </select>
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
                      {countdownTime !== null 
                        ? `${Math.floor(countdownTime / 60)}:${(countdownTime % 60).toString().padStart(2, "0")}`
                        : "Running"}
                    </>
                  ) : (
                    "Submit"
                  )}
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
