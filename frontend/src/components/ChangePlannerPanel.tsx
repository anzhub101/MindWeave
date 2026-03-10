import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, GitBranchPlus, Loader2, Sparkles } from "lucide-react";
import type { PlanChangeResponse } from "../types";

interface ChangePlannerPanelProps {
  offlineDemo: boolean;
  selectedNodeId: string | null;
  selectedNodeTitle: string | null;
  planResult: PlanChangeResponse | null;
  isPlanning: boolean;
  isApplying: boolean;
  onPlanChange: (requestText: string) => Promise<void>;
  onApplyPlannedChange: (proposalId: string, approvedBy: string, autoRerun: boolean) => Promise<void>;
}

function humanize(value: string) {
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function planNarrative(planResult: PlanChangeResponse | null) {
  if (!planResult?.proposal) {
    return planResult?.clarification_question ?? "";
  }
  const patchTypes = planResult.proposal.patches.map((patch) => patch.patch_type);
  const addedNodes = patchTypes.filter((type) => type === "add_node" || type === "insert_node_between").length;
  const expandedNodes = patchTypes.filter((type) => type === "expand_node").length;
  const rerunRequested = patchTypes.includes("rerun_subtree") || planResult.proposal.rerun_scope === "subtree";
  const executorChange = patchTypes.includes("change_executor");
  const evidenceChange = patchTypes.includes("change_evidence_scope");

  const actions: string[] = [];
  if (expandedNodes) {
    actions.push(`expand ${expandedNodes === 1 ? "one branch" : `${expandedNodes} branches`}`);
  }
  if (addedNodes) {
    actions.push(`add ${addedNodes} ${addedNodes === 1 ? "node" : "nodes"}`);
  }
  if (executorChange) {
    actions.push("update executor settings");
  }
  if (evidenceChange) {
    actions.push("change the evidence scope");
  }
  if (rerunRequested) {
    actions.push("rerun the affected subtree");
  }

  if (!actions.length) {
    return planResult.proposal.summary;
  }
  return `This dry-run will ${actions.join(", ")} while preserving graph validation and approval controls.`;
}

export function ChangePlannerPanel({
  offlineDemo,
  selectedNodeId,
  selectedNodeTitle,
  planResult,
  isPlanning,
  isApplying,
  onPlanChange,
  onApplyPlannedChange,
}: ChangePlannerPanelProps) {
  const [requestText, setRequestText] = useState("");
  const [approvedBy, setApprovedBy] = useState("");
  const [autoRerun, setAutoRerun] = useState(true);
  const [isExpanded, setIsExpanded] = useState(!selectedNodeId);

  // Auto-collapse when a node is selected, auto-expand when graph-wide
  useEffect(() => {
    setIsExpanded(!selectedNodeId);
  }, [selectedNodeId]);

  async function handlePreview() {
    if (!requestText.trim() || offlineDemo) {
      return;
    }
    await onPlanChange(requestText.trim());
  }

  async function handleApply() {
    if (!planResult?.proposal) {
      return;
    }
    await onApplyPlannedChange(planResult.proposal.proposal_id, approvedBy.trim(), autoRerun);
  }

  const requiresApproval = Boolean(planResult?.proposal?.requires_approval);
  const isProposalReady = planResult?.status === "proposed" && planResult.proposal && planResult.validation?.status === "valid";
  const narrative = planNarrative(planResult);

  return (
    <section className="rounded-[22px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] uppercase tracking-[0.24em] text-[var(--mw-subtle)]">Adaptive Planner</div>
          <div className="mt-2 font-sans text-[24px] font-semibold leading-none text-[var(--mw-text)]">Change with Prompt</div>
        </div>
        <div className="flex items-center gap-2">
          <div className="rounded-full border border-[var(--mw-border)] px-3 py-1 text-[10px] uppercase tracking-[0.22em] text-[var(--mw-accent)]">
            {selectedNodeId ? `Targeting ${selectedNodeTitle ?? humanize(selectedNodeId)}` : "Graph-Wide"}
          </div>
          {selectedNodeId ? (
            <button
              type="button"
              onClick={() => setIsExpanded((prev) => !prev)}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] text-[var(--mw-muted)] transition hover:border-[var(--mw-accent)] hover:text-[var(--mw-text)]"
            >
              <ChevronDown size={14} className={isExpanded ? "rotate-180 transition" : "transition"} />
            </button>
          ) : null}
        </div>
      </div>

      {isExpanded ? (
        <>
          <div className="mt-4 mw-code-shell rounded-[18px] p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-[var(--mw-code-comment)]">
                <span className="h-2.5 w-2.5 rounded-full bg-[var(--mw-danger)]" />
                <span className="h-2.5 w-2.5 rounded-full bg-[var(--mw-success)]" />
                <span className="h-2.5 w-2.5 rounded-full bg-[var(--mw-accent)]" />
                graph_change.plan
              </div>
              <div className="font-mono text-[11px] text-[var(--mw-code-comment)]">
                {selectedNodeId ? `scope=node:${selectedNodeId}` : "scope=graph"}
              </div>
            </div>
            <div className="mt-3 text-[12px] leading-6 text-[var(--mw-code-comment)]">
              <span className="text-[var(--mw-code-keyword)]">$</span> describe the desired graph mutation in plain language
            </div>
            <textarea
              value={requestText}
              onChange={(event) => setRequestText(event.target.value)}
              rows={5}
              placeholder="expand the fraud branch, rerun only the revenue section, add a controls review node, or tighten evidence scope"
              disabled={offlineDemo || isPlanning || isApplying}
              className="mt-3 w-full resize-none rounded-[14px] border border-[var(--mw-code-border)] bg-[var(--mw-code-panel)] px-4 py-3 font-mono text-[13px] leading-6 text-[var(--mw-code-text)] outline-none transition focus:border-[var(--mw-accent)] placeholder:text-[var(--mw-code-comment)]"
            />
          </div>

          <div className="mt-3 flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => void handlePreview()}
              disabled={offlineDemo || isPlanning || isApplying || !requestText.trim()}
              className="inline-flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isPlanning ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              Compile & Dry-Run
            </button>
          </div>

          {planResult ? (
            <div className="mt-5 space-y-4">
              <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                <div className="flex items-center gap-2 text-[var(--mw-accent)]">
                  {planResult.status === "needs_clarification" ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} />}
                  <span className="text-[11px] uppercase tracking-[0.22em]">
                    {planResult.status === "needs_clarification" ? "Clarification Required" : "Compiled Intent"}
                  </span>
                </div>
                <div className="mt-3 text-[14px] leading-7 text-[var(--mw-text)]">
                  {narrative || planResult.clarification_question || "No dry-run summary is available."}
                </div>
                <div className="mt-3 text-[13px] leading-6 text-[var(--mw-muted)]">
                  <div>Intent: {planResult.intent ? humanize(planResult.intent.intent_type) : "Unavailable"}</div>
                  <div>Target: {planResult.intent?.target_node_id ? humanize(planResult.intent.target_node_id) : "Graph-wide"}</div>
                  <div>Confidence: {planResult.intent ? `${Math.round(planResult.intent.confidence * 100)}%` : "--"}</div>
                </div>
              </div>

              {planResult.proposal ? (
                <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                  <div className="flex items-center gap-2 text-[var(--mw-accent)]">
                    <GitBranchPlus size={15} />
                    <span className="text-[11px] uppercase tracking-[0.22em]">Compiled Patch Set</span>
                  </div>
                  <div className="mt-3 font-sans text-[18px] font-semibold leading-7 text-[var(--mw-text)]">{planResult.proposal.summary}</div>
                  <div className="mt-2 text-[13px] leading-6 text-[var(--mw-muted)]">{planResult.proposal.explanation}</div>
                  <div className="mt-4 space-y-2">
                    {planResult.proposal.patches.map((patch, index) => (
                      <div key={`${patch.patch_type}-${patch.target_node_id ?? "graph"}-${index}`} className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2">
                        <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">{patch.patch_type}</div>
                        <div className="mt-1 text-[13px] leading-6 text-[var(--mw-muted)]">
                          Target: {patch.target_node_id ? humanize(patch.target_node_id) : "Graph-wide"}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              {planResult.validation ? (
                <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                  <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--mw-subtle)]">Validation</div>
                  <div className="mt-2 text-[13px] leading-6 text-[var(--mw-muted)]">
                    Status: {humanize(planResult.validation.status)}
                  </div>
                  {planResult.validation.warnings.length > 0 ? (
                    <div className="mt-3 space-y-2">
                      {planResult.validation.warnings.map((warning) => (
                        <div key={warning} className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[13px] leading-6 text-[var(--mw-muted)]">
                          {warning}
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {planResult.validation.errors.length > 0 ? (
                    <div className="mt-3 space-y-2">
                      {planResult.validation.errors.map((error) => (
                        <div key={error} className="rounded-[14px] border border-[var(--mw-danger)] bg-[var(--mw-danger-soft)] px-3 py-2 text-[13px] leading-6 text-[var(--mw-text)]">
                          {error}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}

              {isProposalReady ? (
                <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--mw-subtle)]">Apply Proposal</div>
                    <div className="mt-1 text-[13px] leading-6 text-[var(--mw-muted)]">
                      {requiresApproval
                        ? "Approval is required before this patch can be applied. An approver ID must be supplied."
                        : "This proposal can be applied directly."}
                    </div>
                  </div>
                  {requiresApproval ? (
                    <input
                      value={approvedBy}
                      onChange={(event) => setApprovedBy(event.target.value)}
                      placeholder="Approver ID"
                      className="mt-3 w-full rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 font-mono text-[13px] leading-6 text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
                    />
                  ) : null}
                  <label className="mt-3 flex items-center gap-2 text-[12px] uppercase tracking-[0.14em] text-[var(--mw-subtle)]">
                    <input
                      type="checkbox"
                      checked={autoRerun}
                      onChange={(event) => setAutoRerun(event.target.checked)}
                      className="h-4 w-4 rounded border-[var(--mw-border)] bg-[var(--mw-panel)]"
                    />
                    Auto rerun affected scope
                  </label>
                  <button
                    type="button"
                    onClick={() => void handleApply()}
                    disabled={isApplying || (requiresApproval && !approvedBy.trim())}
                    className="mt-4 inline-flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isApplying ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                    Apply Planned Change
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}