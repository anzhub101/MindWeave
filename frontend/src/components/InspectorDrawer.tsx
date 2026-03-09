import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Sparkles,
  UserRound,
  Wrench,
  X,
} from "lucide-react";
import type { GraphNode, NodeDetailResponse, PlanChangeResponse } from "../types";

interface InspectorDrawerProps {
  node: GraphNode;
  nodeDetail: NodeDetailResponse | null;
  planResult: PlanChangeResponse | null;
  isLoading: boolean;
  isPlanning: boolean;
  isApplying: boolean;
  isUpdatingExecutor: boolean;
  onPlanNodeChange: (nodeId: string, requestText: string) => Promise<void>;
  onApplyPlannedChange: (proposalId: string, approvedBy: string, autoRerun: boolean) => Promise<void>;
  onChangeExecutor: (
    nodeId: string,
    payload: {
      executor_type: string;
      executor_profile?: string | null;
      max_child_agents?: number;
      max_recursion_depth?: number;
      child_token_budget?: number;
      delegated_summary_required?: boolean;
      change_reason?: string;
      instruction_note?: string;
      auto_rerun?: boolean;
    },
  ) => Promise<void>;
  onClose: () => void;
}

function humanize(value: string | null | undefined) {
  if (!value) {
    return "Unavailable";
  }
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function statusTone(status: string) {
  if (status === "approved" || status === "passed" || status === "completed") {
    return "text-[var(--mw-accent)]";
  }
  if (status === "failed" || status === "rejected") {
    return "text-[color:rgba(190,111,93,1)]";
  }
  return "text-[var(--mw-text)]";
}

function executorIcon(executorType: string | null | undefined) {
  if (executorType === "agent_operator") {
    return <Bot size={14} strokeWidth={1.8} />;
  }
  if (executorType === "tool_operator") {
    return <Wrench size={14} strokeWidth={1.8} />;
  }
  if (executorType === "human_operator") {
    return <UserRound size={14} strokeWidth={1.8} />;
  }
  return <Sparkles size={14} strokeWidth={1.8} />;
}

function prettyJson(value: unknown) {
  return JSON.stringify(value, null, 2);
}

function evidenceLocation(reference: { page: number | null; char_start: number | null; char_end: number | null }) {
  if (typeof reference.page === "number") {
    return `Page ${reference.page}`;
  }
  if (typeof reference.char_start === "number" && typeof reference.char_end === "number") {
    return `Chars ${reference.char_start}-${reference.char_end}`;
  }
  return "Location unavailable";
}

function Section({
  title,
  eyebrow,
  children,
}: {
  title: string;
  eyebrow: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[20px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
      <div className="text-[10px] uppercase tracking-[0.22em] text-[var(--mw-subtle)]">{eyebrow}</div>
      <div className="mt-2 font-serif text-[22px] leading-none text-[var(--mw-text)]">{title}</div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Metric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
      <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">{label}</div>
      <div className="mt-2 text-[14px] leading-6 text-[var(--mw-text)]">{value}</div>
    </div>
  );
}

export function InspectorDrawer({
  node,
  nodeDetail,
  planResult,
  isLoading,
  isPlanning,
  isApplying,
  isUpdatingExecutor,
  onPlanNodeChange,
  onApplyPlannedChange,
  onChangeExecutor,
  onClose,
}: InspectorDrawerProps) {
  const detail = nodeDetail?.node ?? node;
  const scopedPlan = planResult?.intent?.target_node_id === detail.id ? planResult : null;
  const topEvidence = nodeDetail?.top_evidence ?? detail.evidence_refs.slice(0, 3);
  const findings = nodeDetail?.finding_records ?? detail.finding_records ?? [];
  const approvalState = nodeDetail?.approval_state ?? detail.approval_state;
  const technicalDetails = nodeDetail?.technical_details ?? {};
  const patchHistory = nodeDetail?.patch_history ?? [];
  const delegatedChildren = nodeDetail?.delegated_children ?? detail.delegated_children ?? [];

  const [executorType, setExecutorType] = useState(detail.executor_type ?? "llm_operator");
  const [executorProfile, setExecutorProfile] = useState(detail.executor_profile ?? "");
  const [maxChildAgents, setMaxChildAgents] = useState(detail.max_child_agents ?? 0);
  const [maxRecursionDepth, setMaxRecursionDepth] = useState(detail.max_recursion_depth ?? 0);
  const [childTokenBudget, setChildTokenBudget] = useState(detail.child_token_budget ?? 0);
  const [delegatedSummaryRequired, setDelegatedSummaryRequired] = useState(detail.delegated_summary_required ?? false);
  const [changeRequest, setChangeRequest] = useState("");
  const [approverId, setApproverId] = useState("");
  const [autoRerun, setAutoRerun] = useState(true);

  useEffect(() => {
    setExecutorType(detail.executor_type ?? "llm_operator");
    setExecutorProfile(detail.executor_profile ?? "");
    setMaxChildAgents(detail.max_child_agents ?? 0);
    setMaxRecursionDepth(detail.max_recursion_depth ?? 0);
    setChildTokenBudget(detail.child_token_budget ?? 0);
    setDelegatedSummaryRequired(detail.delegated_summary_required ?? false);
  }, [
    detail.child_token_budget,
    detail.delegated_summary_required,
    detail.executor_profile,
    detail.executor_type,
    detail.id,
    detail.max_child_agents,
    detail.max_recursion_depth,
  ]);

  const keyConclusion = useMemo(() => {
    return (
      nodeDetail?.key_conclusion ||
      (typeof detail.output?.conclusion === "string" ? detail.output.conclusion : "") ||
      detail.thought_summary ||
      detail.subtitle
    );
  }, [detail.output, detail.subtitle, detail.thought_summary, nodeDetail?.key_conclusion]);

  const requiresApproval = Boolean(scopedPlan?.proposal?.requires_approval);
  const proposalReady = scopedPlan?.status === "proposed" && scopedPlan.proposal && scopedPlan.validation?.status === "valid";
  const agentActive = executorType === "agent_operator";

  async function handlePreviewChange() {
    if (!changeRequest.trim()) {
      return;
    }
    await onPlanNodeChange(detail.id, changeRequest.trim());
  }

  async function handleApplyPlan() {
    if (!scopedPlan?.proposal) {
      return;
    }
    await onApplyPlannedChange(scopedPlan.proposal.proposal_id, approverId.trim(), autoRerun);
  }

  async function handleApplyExecutor() {
    await onChangeExecutor(detail.id, {
      executor_type: executorType,
      executor_profile: executorProfile || null,
      max_child_agents: agentActive ? maxChildAgents : 0,
      max_recursion_depth: agentActive ? maxRecursionDepth : 0,
      child_token_budget: agentActive ? childTokenBudget : 0,
      delegated_summary_required: agentActive ? delegatedSummaryRequired : false,
      change_reason: `Update executor settings for ${detail.id}.`,
      auto_rerun: true,
    });
  }

  async function handleToggleAgent() {
    const nextExecutorType = detail.executor_type === "agent_operator" ? "llm_operator" : "agent_operator";
    await onChangeExecutor(detail.id, {
      executor_type: nextExecutorType,
      executor_profile: nextExecutorType === "agent_operator" ? executorProfile || "general" : null,
      max_child_agents: nextExecutorType === "agent_operator" ? Math.max(maxChildAgents, 1) : 0,
      max_recursion_depth: nextExecutorType === "agent_operator" ? Math.max(maxRecursionDepth, 1) : 0,
      child_token_budget: nextExecutorType === "agent_operator" ? Math.max(childTokenBudget, 4000) : 0,
      delegated_summary_required: nextExecutorType === "agent_operator",
      change_reason:
        nextExecutorType === "agent_operator"
          ? `Activate agent delegation for ${detail.id}.`
          : `Deactivate agent delegation for ${detail.id}.`,
      auto_rerun: true,
    });
  }

  return (
    <section className="flex shrink-0 flex-col rounded-[18px] bg-[var(--mw-panel)]">
      <div className="border-b border-[var(--mw-border)] px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-[11px] font-medium uppercase tracking-[0.26em] text-[var(--mw-accent)]">
              Node Operations
            </div>
            <div className="mt-1 font-serif text-[26px] leading-none tracking-[-0.03em] text-[var(--mw-text)]">
              {detail.title}
            </div>
            <div className="mt-2 text-[13px] leading-6 text-[var(--mw-subtle)]">{detail.subtitle}</div>
          </div>

          <div className="flex items-center gap-2">
            <div className="inline-flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-1.5 text-[11px] uppercase tracking-[0.16em] text-[var(--mw-text)]">
              {executorIcon(detail.executor_type)}
              {humanize(detail.executor_type)}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="flex h-10 w-10 items-center justify-center rounded-2xl border border-[var(--mw-border)] bg-[var(--mw-panel)] text-[var(--mw-muted)] transition hover:text-[var(--mw-text)]"
            >
              <X size={16} strokeWidth={1.8} />
            </button>
          </div>
        </div>
      </div>

      <div className="space-y-4 px-5 py-4">
        {isLoading ? (
          <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3 text-[13px] leading-6 text-[var(--mw-muted)]">
            Loading focused node detail...
          </div>
        ) : null}

        <Section title="Overview" eyebrow="What This Node Is">
          <div className="grid gap-3 sm:grid-cols-2">
            <Metric label="Operation" value={humanize(detail.operation_type)} />
            <Metric label="Status" value={humanize(detail.status)} />
            <Metric label="Verification" value={humanize(detail.verification_status)} />
            <Metric label="Evidence" value={`${nodeDetail?.evidence_count ?? detail.evidence_refs.length} linked`} />
            <Metric
              label="Approval"
              value={
                approvalState
                  ? `${humanize(approvalState.status)} (${approvalState.approved_count}/${approvalState.required_approvals})`
                  : "Not required"
              }
            />
            <Metric
              label="Latency"
              value={detail.latency_ms ? `${(detail.latency_ms / 1000).toFixed(2)}s` : "Unavailable"}
            />
          </div>
        </Section>

        <Section title="Reasoning Summary" eyebrow="Most Relevant Output">
          <div className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
            <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Thought Summary</div>
            <div className="mt-2 text-[14px] leading-7 text-[var(--mw-text)]">
              {detail.thought_summary || "No summary was recorded for this node."}
            </div>
          </div>
          <div className="mt-3 rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
            <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Key Conclusion</div>
            <div className="mt-2 text-[14px] leading-7 text-[var(--mw-text)]">{keyConclusion || "No conclusion recorded."}</div>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Metric
              label="Evaluation"
              value={typeof detail.evaluation_score === "number" ? detail.evaluation_score.toFixed(2) : "Unavailable"}
            />
            <Metric label="Delegated Children" value={`${delegatedChildren.length}`} />
          </div>
          {findings.length ? (
            <div className="mt-3 space-y-2">
              {findings.slice(0, 3).map((finding) => (
                <div key={finding.id} className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                  <div className="text-[14px] leading-6 text-[var(--mw-text)]">{finding.text}</div>
                  <div className="mt-2 text-[11px] uppercase tracking-[0.14em] text-[var(--mw-subtle)]">
                    {humanize(finding.claim_classification)} · {humanize(finding.support_level)}
                  </div>
                </div>
              ))}
            </div>
          ) : null}
        </Section>

        <Section title="Evidence" eyebrow="Top Linked Support">
          <div className="space-y-3">
            {topEvidence.length ? (
              topEvidence.map((reference) => (
                <div key={reference.id} className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                  <div className="text-[14px] leading-6 text-[var(--mw-text)]">
                    {reference.document_name || reference.document_id}
                  </div>
                  <div className="mt-1 text-[13px] leading-6 text-[var(--mw-muted)]">
                    {reference.chunk_id} · {humanize(reference.support_level)} · {evidenceLocation(reference)}
                  </div>
                </div>
              ))
            ) : (
              <div className="text-[14px] leading-7 text-[var(--mw-muted)]">No linked evidence was recorded for this node.</div>
            )}
          </div>
        </Section>

        <Section title="Execution Mode" eyebrow="Agent And Executor Controls">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
              <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Executor Type</div>
              <select
                value={executorType}
                onChange={(event) => setExecutorType(event.target.value)}
                className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
              >
                <option value="llm_operator">LLM</option>
                <option value="agent_operator">Agent</option>
                <option value="tool_operator">Tool</option>
                <option value="human_operator">Human</option>
              </select>
            </label>

            <label className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
              <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Agent Profile</div>
              <select
                value={executorProfile}
                onChange={(event) => setExecutorProfile(event.target.value)}
                className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
              >
                <option value="">General</option>
                <option value="forensic">Forensic</option>
                <option value="controls">Controls</option>
                <option value="revenue">Revenue</option>
              </select>
            </label>
          </div>

          {agentActive ? (
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <label className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Max Child Agents</div>
                <input
                  type="number"
                  min={0}
                  value={maxChildAgents}
                  onChange={(event) => setMaxChildAgents(Number(event.target.value))}
                  className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                />
              </label>
              <label className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Recursion Depth</div>
                <input
                  type="number"
                  min={0}
                  value={maxRecursionDepth}
                  onChange={(event) => setMaxRecursionDepth(Number(event.target.value))}
                  className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                />
              </label>
              <label className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Child Token Budget</div>
                <input
                  type="number"
                  min={0}
                  value={childTokenBudget}
                  onChange={(event) => setChildTokenBudget(Number(event.target.value))}
                  className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                />
              </label>
            </div>
          ) : null}

          <label className="mt-3 flex items-center gap-2 text-[12px] uppercase tracking-[0.14em] text-[var(--mw-subtle)]">
            <input
              type="checkbox"
              checked={delegatedSummaryRequired}
              onChange={(event) => setDelegatedSummaryRequired(event.target.checked)}
              className="h-4 w-4 accent-[var(--mw-accent)]"
            />
            Require child summary return
          </label>

          <div className="mt-4 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void handleApplyExecutor()}
              disabled={isUpdatingExecutor}
              className="rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isUpdatingExecutor ? "Updating..." : "Apply Execution Mode"}
            </button>
            <button
              type="button"
              onClick={() => void handleToggleAgent()}
              disabled={isUpdatingExecutor}
              className="rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {detail.executor_type === "agent_operator" ? "Deactivate Agent" : "Activate Agent"}
            </button>
          </div>
        </Section>

        <Section title="Change This Node" eyebrow="Natural-Language Planner">
          <textarea
            value={changeRequest}
            onChange={(event) => setChangeRequest(event.target.value)}
            rows={4}
            placeholder="Expand this node, rerun the subtree, change evidence scope, or switch the executor."
            className="w-full resize-none rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3 text-[14px] leading-6 text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
          />
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void handlePreviewChange()}
              disabled={isPlanning || !changeRequest.trim()}
              className="rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isPlanning ? "Planning..." : "Preview Change"}
            </button>
          </div>

          {scopedPlan ? (
            <div className="mt-4 space-y-3">
              <div className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                <div className="flex items-center gap-2 text-[var(--mw-accent)]">
                  {scopedPlan.status === "needs_clarification" ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} />}
                  <span className="text-[11px] uppercase tracking-[0.18em]">
                    {scopedPlan.status === "needs_clarification" ? "Clarification Required" : "Preview Ready"}
                  </span>
                </div>
                <div className="mt-2 text-[13px] leading-6 text-[var(--mw-muted)]">
                  {scopedPlan.proposal?.summary || scopedPlan.clarification_question || "No proposal summary available."}
                </div>
              </div>

              {scopedPlan.validation?.warnings.length ? (
                <div className="space-y-2">
                  {scopedPlan.validation.warnings.map((warning) => (
                    <div key={warning} className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[13px] leading-6 text-[var(--mw-muted)]">
                      {warning}
                    </div>
                  ))}
                </div>
              ) : null}

              {proposalReady ? (
                <div className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                  {requiresApproval ? (
                    <input
                      value={approverId}
                      onChange={(event) => setApproverId(event.target.value)}
                      placeholder="Approver ID"
                      className="w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                    />
                  ) : null}
                  <label className="mt-3 flex items-center gap-2 text-[12px] uppercase tracking-[0.14em] text-[var(--mw-subtle)]">
                    <input
                      type="checkbox"
                      checked={autoRerun}
                      onChange={(event) => setAutoRerun(event.target.checked)}
                      className="h-4 w-4 accent-[var(--mw-accent)]"
                    />
                    Auto rerun affected scope
                  </label>
                  <button
                    type="button"
                    onClick={() => void handleApplyPlan()}
                    disabled={isApplying || (requiresApproval && !approverId.trim())}
                    className="mt-4 rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isApplying ? "Applying..." : "Apply Validated Change"}
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </Section>

        <Section title="Governance" eyebrow="Checks And Approvals">
          <div className="grid gap-3 sm:grid-cols-2">
            <Metric
              label="Approval State"
              value={approvalState ? `${humanize(approvalState.status)} (${approvalState.pending_approvals} pending)` : "Not required"}
            />
            <Metric label="Delegated Children" value={`${delegatedChildren.length}`} />
          </div>
          {(detail.verification_checks?.length || patchHistory.length) ? (
            <div className="mt-3 grid gap-3">
              {detail.verification_checks?.length ? (
                <div className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Key Verification Checks</div>
                  <div className="mt-2 space-y-1 text-[13px] leading-6 text-[var(--mw-muted)]">
                    {detail.verification_checks.slice(0, 4).map((check) => (
                      <div key={check}>{check}</div>
                    ))}
                  </div>
                </div>
              ) : null}

              {patchHistory.length ? (
                <div className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Patch History</div>
                  <div className="mt-2 space-y-2 text-[13px] leading-6 text-[var(--mw-muted)]">
                    {patchHistory.slice(-3).reverse().map((patch) => (
                      <div key={patch.patch_id}>
                        {humanize(patch.patch_type)} · {patch.change_reason}
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="mt-3 text-[14px] leading-7 text-[var(--mw-muted)]">No additional governance detail is recorded for this node.</div>
          )}
        </Section>

        <Section title="Technical Details" eyebrow="Collapsed By Default">
          <div className="space-y-3">
            <details className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
              <summary className="cursor-pointer text-[12px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                Full Structured Inputs
              </summary>
              <pre className="mt-3 overflow-x-auto text-[11px] leading-6 text-[var(--mw-muted)]">
                {prettyJson(technicalDetails.inputs ?? detail.inputs)}
              </pre>
            </details>
            <details className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
              <summary className="cursor-pointer text-[12px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                Full Structured Output
              </summary>
              <pre className="mt-3 overflow-x-auto text-[11px] leading-6 text-[var(--mw-muted)]">
                {prettyJson(technicalDetails.output ?? detail.output)}
              </pre>
            </details>
            <details className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
              <summary className="cursor-pointer text-[12px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                Model Metadata
              </summary>
              <pre className="mt-3 overflow-x-auto text-[11px] leading-6 text-[var(--mw-muted)]">
                {prettyJson(technicalDetails.model_metadata ?? detail.model_metadata ?? {})}
              </pre>
            </details>
            <details className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
              <summary className="cursor-pointer text-[12px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                Verification Details
              </summary>
              <pre className="mt-3 overflow-x-auto text-[11px] leading-6 text-[var(--mw-muted)]">
                {prettyJson(technicalDetails.verification_checks ?? detail.verification_checks ?? [])}
              </pre>
            </details>
            <details className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
              <summary className="cursor-pointer text-[12px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                Full Patch History
              </summary>
              <pre className="mt-3 overflow-x-auto text-[11px] leading-6 text-[var(--mw-muted)]">
                {prettyJson(patchHistory)}
              </pre>
            </details>
          </div>
        </Section>
      </div>
    </section>
  );
}
