import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { LoaderCircle, Upload, ChevronDown, ChevronUp } from "lucide-react";

interface PromptComposerProps {
  prompt: string;
  onPromptChange: (value: string) => void;
  onSubmit: () => void;
  onFileSelect: (files: File[]) => void;
  determinismMode: "non_deterministic" | "best_effort_deterministic" | "strict_deterministic";
  onDeterminismModeChange: (value: "non_deterministic" | "best_effort_deterministic" | "strict_deterministic") => void;
  controlLevel: "exploratory" | "operational" | "regulated" | "strict_audit";
  onControlLevelChange: (value: "exploratory" | "operational" | "regulated" | "strict_audit") => void;
  autoApproveHumanReview: boolean;
  onAutoApproveHumanReviewChange: (value: boolean) => void;
  files: File[];
  isSubmitting: boolean;
  offlineDemo: boolean;
  isNodeSelected?: boolean; // New prop
}

export function PromptComposer({
  prompt,
  onPromptChange,
  onSubmit,
  onFileSelect,
  determinismMode,
  onDeterminismModeChange,
  controlLevel,
  onControlLevelChange,
  autoApproveHumanReview,
  onAutoApproveHumanReviewChange,
  files,
  isSubmitting,
  offlineDemo,
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
          <div className="mt-1 flex items-center gap-2 font-serif text-[22px] leading-none text-[var(--mw-text)]">
            Prompt
            {isExpanded ? (
              <ChevronUp size={16} className="text-[var(--mw-subtle)] transition hover:text-[var(--mw-text)]" />
            ) : (
              <ChevronDown size={16} className="text-[var(--mw-subtle)] transition hover:text-[var(--mw-text)]" />
            )}
          </div>
        </div>

        {offlineDemo && (
          <div className="rounded-full border border-[var(--mw-border)] bg-[var(--mw-accent-soft)] px-3 py-2 text-[10px] uppercase tracking-[0.22em] text-[var(--mw-accent)]">
            Offline demo mode
          </div>
        )}
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

            <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
              <div className="space-y-3">
                <div className="text-[13px] text-[var(--mw-subtle)]">
                  {files.length > 0
                    ? `${files.length} document${files.length === 1 ? "" : "s"} attached`
                    : "No uploads attached. The bundled sample pack will be used."}
                </div>
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
                      Running
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
