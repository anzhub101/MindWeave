import { useState } from "react";
import { AlertTriangle, CheckCircle2, GitBranchPlus, Loader2, Sparkles } from "lucide-react";
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

  return (
    <section className="rounded-[22px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-[0.24em] text-[var(--mw-subtle)]">Adaptive Planner</div>
          <div className="mt-2 font-serif text-[24px] leading-none text-[var(--mw-text)]">Natural-Language Change Plan</div>
        </div>
        <div className="rounded-full border border-[var(--mw-border)] px-3 py-1 text-[10px] uppercase tracking-[0.22em] text-[var(--mw-accent)]">
          {selectedNodeId ? `Targeting ${selectedNodeTitle ?? humanize(selectedNodeId)}` : "Graph-Wide"}
        </div>
      </div>

      <div className="mt-4 space-y-3">
        <textarea
          value={requestText}
          onChange={(event) => setRequestText(event.target.value)}
          rows={4}
          placeholder="Expand the fraud branch, re-run only analysis, add a controls review node, or tighten evidence scope."
          disabled={offlineDemo || isPlanning || isApplying}
          className="w-full resize-none rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3 text-[14px] leading-6 text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
        />

        <div className="flex items-center justify-between gap-3">
          <div className="text-[12px] leading-5 text-[var(--mw-subtle)]">
            {offlineDemo
              ? "Planner preview is disabled while the dashboard is using offline demo data."
              : "Requests are translated into reviewed patch proposals before anything is applied."}
          </div>
          <button
            type="button"
            onClick={() => void handlePreview()}
            disabled={offlineDemo || isPlanning || isApplying || !requestText.trim()}
            className="inline-flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isPlanning ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            Preview Change
          </button>
        </div>
      </div>

      {planResult ? (
        <div className="mt-5 space-y-4">
          <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
            <div className="flex items-center gap-2 text-[var(--mw-accent)]">
              {planResult.status === "needs_clarification" ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} />}
              <span className="text-[11px] uppercase tracking-[0.22em]">
                {planResult.status === "needs_clarification" ? "Clarification Required" : "Parsed Intent"}
              </span>
            </div>
            <div className="mt-3 text-[13px] leading-6 text-[var(--mw-muted)]">
              <div>Type: {planResult.intent ? humanize(planResult.intent.intent_type) : "Unavailable"}</div>
              <div>Target: {planResult.intent?.target_node_id ? humanize(planResult.intent.target_node_id) : "Graph-wide"}</div>
              <div>Confidence: {planResult.intent ? `${Math.round(planResult.intent.confidence * 100)}%` : "--"}</div>
            </div>
            {planResult.clarification_question ? (
              <div className="mt-3 rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[13px] leading-6 text-[var(--mw-text)]">
                {planResult.clarification_question}
              </div>
            ) : null}
          </div>

          {planResult.proposal ? (
            <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
              <div className="flex items-center gap-2 text-[var(--mw-accent)]">
                <GitBranchPlus size={15} />
                <span className="text-[11px] uppercase tracking-[0.22em]">Patch Proposal</span>
              </div>
              <div className="mt-3 font-serif text-[18px] leading-7 text-[var(--mw-text)]">{planResult.proposal.summary}</div>
              <div className="mt-2 text-[13px] leading-6 text-[var(--mw-muted)]">{planResult.proposal.explanation}</div>
              <div className="mt-4 space-y-2">
                {planResult.proposal.patches.map((patch, index) => (
                  <div key={`${patch.patch_type}-${patch.target_node_id ?? "graph"}-${index}`} className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2">
                    <div className="text-[11px] uppercase tracking-[0.2em] text-[var(--mw-subtle)]">{humanize(patch.patch_type)}</div>
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
                    <div key={error} className="rounded-[14px] border border-[rgba(190,111,93,0.28)] bg-[rgba(190,111,93,0.10)] px-3 py-2 text-[13px] leading-6 text-[var(--mw-text)]">
                      {error}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          {isProposalReady ? (
            <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--mw-subtle)]">Apply Proposal</div>
                  <div className="mt-1 text-[13px] leading-6 text-[var(--mw-muted)]">
                    {requiresApproval ? "Approval is required before this patch can be applied." : "This proposal can be applied directly."}
                  </div>
                </div>
              </div>
              {requiresApproval ? (
                <input
                  value={approvedBy}
                  onChange={(event) => setApprovedBy(event.target.value)}
                  placeholder="Approver ID"
                  className="mt-3 w-full rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[13px] leading-6 text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
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
    </section>
  );
}
