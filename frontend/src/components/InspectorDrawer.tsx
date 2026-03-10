import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronDown,
  Circle,
  Loader2,
  Send,
  ShieldCheck,
  Sparkles,
  UserRound,
  Wrench,
  X,
} from "lucide-react";
import type { GraphNode, NodeChatMessage, NodeChatResponse, NodeDetailResponse, SkillSummary } from "../types";

interface InspectorDrawerProps {
  node: GraphNode;
  nodeDetail: NodeDetailResponse | null;
  isLoading: boolean;
  isUpdatingExecutor: boolean;
  isPassing: boolean;
  isChatting: boolean;
  chatMessages: NodeChatMessage[];
  chatResponse: NodeChatResponse | null;
  availableSkills: SkillSummary[];
  onChangeExecutor: (
    nodeId: string,
    payload: {
      executor_type: string;
      executor_profile?: string | null;
      skill_artifact_id?: string | null;
      max_child_agents?: number;
      max_recursion_depth?: number;
      child_token_budget?: number;
      delegated_summary_required?: boolean;
      change_reason?: string;
      instruction_note?: string;
      auto_rerun?: boolean;
    },
  ) => Promise<void>;
  onPassAndVerifyNode: (nodeId: string) => Promise<void>;
  onSendChat: (nodeId: string, message: string) => Promise<void>;
  onOpenSkillsWorkspace: () => void;
  onClose: () => void;
}

function humanize(value: string | null | undefined) {
  if (!value) {
    return "Unavailable";
  }
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
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

function relativeTime(value: string | null | undefined) {
  if (!value) {
    return "pending";
  }
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) {
    return value;
  }
  const deltaSeconds = Math.max(0, Math.round((Date.now() - timestamp.getTime()) / 1000));
  if (deltaSeconds < 60) {
    return `${deltaSeconds}s ago`;
  }
  if (deltaSeconds < 3600) {
    return `${Math.round(deltaSeconds / 60)}m ago`;
  }
  if (deltaSeconds < 86400) {
    return `${Math.round(deltaSeconds / 3600)}h ago`;
  }
  return `${Math.round(deltaSeconds / 86400)}d ago`;
}

function extractWebSearchResults(toolResults: Array<Record<string, unknown>> | undefined) {
  const referrals: Array<{ title: string; url: string; snippet: string }> = [];
  for (const result of toolResults ?? []) {
    if (String(result.tool ?? result.name ?? "") !== "web_search") {
      continue;
    }
    const items = Array.isArray(result.results) ? result.results : [];
    for (const item of items) {
      if (!item || typeof item !== "object") {
        continue;
      }
      const entry = item as Record<string, unknown>;
      const url = String(entry.url ?? "").trim();
      const title = String(entry.title ?? entry.url ?? "Web result").trim();
      const snippet = String(entry.snippet ?? entry.description ?? "").trim();
      if (!title && !url) {
        continue;
      }
      referrals.push({ title: title || url, url, snippet });
    }
  }
  return referrals.slice(0, 4);
}

function executorLabel(executorType: string | null | undefined) {
  if (executorType === "agent_operator") {
    return "Agent";
  }
  if (executorType === "tool_operator") {
    return "Tool";
  }
  if (executorType === "human_operator") {
    return "Human";
  }
  return "LLM";
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

function canPassNode(
  node: GraphNode,
  approvalState: NodeDetailResponse["approval_state"] | GraphNode["approval_state"] | undefined,
) {
  return (
    node.status !== "completed" ||
    node.verification_status !== "passed" ||
    Boolean((approvalState?.pending_approvals ?? 0) > 0)
  );
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
      <div className="mt-2 font-sans text-[22px] font-semibold leading-none text-[var(--mw-text)]">{title}</div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Badge({
  tone = "neutral",
  icon,
  children,
}: {
  tone?: "neutral" | "info" | "success" | "danger";
  icon?: ReactNode;
  children: ReactNode;
}) {
  const toneClass =
    tone === "success"
      ? "border-[var(--mw-success)] bg-[var(--mw-success-soft)] text-[var(--mw-success)]"
      : tone === "danger"
        ? "border-[var(--mw-danger)] bg-[var(--mw-danger-soft)] text-[var(--mw-danger)]"
        : tone === "info"
          ? "border-[var(--mw-accent)] bg-[var(--mw-accent-soft)] text-[var(--mw-accent)]"
          : "border-[var(--mw-border)] bg-[var(--mw-node)] text-[var(--mw-text)]";

  return (
    <div className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] uppercase tracking-[0.16em] ${toneClass}`}>
      {icon}
      {children}
    </div>
  );
}

function Metric({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
      <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">{label}</div>
      <div className={`mt-2 text-[14px] leading-6 text-[var(--mw-text)] ${mono ? "font-mono" : ""}`}>{value}</div>
    </div>
  );
}

export function InspectorDrawer({
  node,
  nodeDetail,
  isLoading,
  isUpdatingExecutor,
  isPassing,
  isChatting,
  chatMessages,
  chatResponse,
  availableSkills,
  onChangeExecutor,
  onPassAndVerifyNode,
  onSendChat,
  onOpenSkillsWorkspace,
  onClose,
}: InspectorDrawerProps) {
  const detail = nodeDetail?.node ?? node;
  const topEvidence = nodeDetail?.top_evidence ?? detail.evidence_refs.slice(0, 3);
  const findings = nodeDetail?.finding_records ?? detail.finding_records ?? [];
  const approvalState = nodeDetail?.approval_state ?? detail.approval_state;
  const approvalReviewers = nodeDetail?.approval_reviewers ?? [];
  const technicalDetails = nodeDetail?.technical_details ?? {};
  const patchHistory = nodeDetail?.patch_history ?? [];
  const delegatedChildren = nodeDetail?.delegated_children ?? detail.delegated_children ?? [];
  const reasoningTrace = nodeDetail?.reasoning_trace ?? detail.reasoning_trace ?? null;
  const modelVersion =
    String((detail.model_metadata?.["model_version"] as string | undefined) || (detail.model_metadata?.["model_id"] as string | undefined) || "runtime");
  const lastGovernancePatch = [...patchHistory].reverse().find(
    (patch) =>
      ["change_executor", "change_policy", "insert_node_between", "add_node", "remove_node"].includes(patch.patch_type) ||
      Boolean(patch.approved_by),
  );

  const [executorType, setExecutorType] = useState(detail.executor_type ?? "llm_operator");
  const [executorProfile, setExecutorProfile] = useState(detail.executor_profile ?? "");
  const [selectedSkillId, setSelectedSkillId] = useState(String(detail.metadata?.skill_artifact_id ?? ""));
  const [maxChildAgents, setMaxChildAgents] = useState(detail.max_child_agents ?? 0);
  const [maxRecursionDepth, setMaxRecursionDepth] = useState(detail.max_recursion_depth ?? 0);
  const [childTokenBudget, setChildTokenBudget] = useState(detail.child_token_budget ?? 0);
  const [delegatedSummaryRequired, setDelegatedSummaryRequired] = useState(detail.delegated_summary_required ?? false);
  const [chatInput, setChatInput] = useState("");
  const [showAdvancedExecution, setShowAdvancedExecution] = useState(false);
  const [showReasoningSummary, setShowReasoningSummary] = useState(false);

  useEffect(() => {
    setExecutorType(detail.executor_type ?? "llm_operator");
    setExecutorProfile(detail.executor_profile ?? "");
    setSelectedSkillId(String(detail.metadata?.skill_artifact_id ?? ""));
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
    detail.metadata,
    detail.max_child_agents,
    detail.max_recursion_depth,
  ]);

  const keyConclusion = useMemo(() => {
    return (
      nodeDetail?.key_conclusion ||
      (typeof detail.output?.["conclusion"] === "string" ? (detail.output["conclusion"] as string) : "") ||
      detail.thought_summary ||
      detail.subtitle
    );
  }, [detail.output, detail.subtitle, detail.thought_summary, nodeDetail?.key_conclusion]);

  const agentActive = executorType === "agent_operator";
  const nodeCanPass = canPassNode(detail, approvalState);
  const attachedSkill = availableSkills.find((skill) => skill.skill_id === selectedSkillId) ?? null;
  const webReferrals = useMemo(() => extractWebSearchResults(chatResponse?.tool_results), [chatResponse?.tool_results]);

  async function handleApplyExecutor() {
    await onChangeExecutor(detail.id, {
      executor_type: executorType,
      executor_profile: executorProfile || null,
      skill_artifact_id: selectedSkillId || null,
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
      skill_artifact_id: selectedSkillId || null,
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

  async function handleSendChat() {
    if (!chatInput.trim()) {
      return;
    }
    const message = chatInput.trim();
    setChatInput("");
    await onSendChat(detail.id, message);
  }

  return (
    <section className="flex shrink-0 flex-col rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)]">
      <div className="border-b border-[var(--mw-border)] px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-[0.24em] text-[var(--mw-accent)]">Node Operations</div>
            <div className="mt-3 flex flex-wrap items-end gap-3">
              <div className="font-sans text-[28px] font-semibold leading-none tracking-[-0.03em] text-[var(--mw-text)]">
                {detail.title}
              </div>
              <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-[var(--mw-subtle)]">
                {detail.id} · {modelVersion} · {relativeTime(detail.completed_at as string | null | undefined)}
              </div>
            </div>
            <div className="mt-2 text-[13px] leading-6 text-[var(--mw-muted)]">{detail.subtitle}</div>
          </div>

          <div className="flex items-center gap-2">
            <Badge tone="info" icon={executorIcon(detail.executor_type)}>
              {executorLabel(detail.executor_type)}
            </Badge>
            <button
              type="button"
              onClick={onClose}
              className="flex h-10 w-10 items-center justify-center rounded-2xl border border-[var(--mw-border)] bg-[var(--mw-panel)] text-[var(--mw-muted)] transition hover:border-[var(--mw-accent)] hover:text-[var(--mw-text)]"
            >
              <X size={16} strokeWidth={1.8} />
            </button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Badge tone={detail.status === "completed" ? "success" : detail.status === "failed" ? "danger" : "neutral"}>
            {detail.status === "completed" ? <CheckCircle2 size={14} strokeWidth={1.8} /> : <Circle size={14} strokeWidth={1.5} />}
            {humanize(detail.status)}
          </Badge>
          <Badge tone={detail.verification_status === "passed" ? "success" : detail.verification_status === "failed" ? "danger" : "neutral"}>
            <ShieldCheck size={14} strokeWidth={1.8} />
            {humanize(detail.verification_status)}
          </Badge>
          <Badge tone={approvalState?.pending_approvals ? "danger" : "neutral"}>
            Approval {approvalState ? `${approvalState.approved_count}/${approvalState.required_approvals}` : "0/0"}
          </Badge>
          <Badge>{nodeDetail?.evidence_count ?? detail.evidence_refs.length} Evidence</Badge>
          <Badge>
            <span className="font-mono">{detail.latency_ms ? `${(detail.latency_ms / 1000).toFixed(2)}s` : "--"}</span>
          </Badge>
        </div>
      </div>

      <div className="space-y-4 px-5 py-4">
        {isLoading ? (
          <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3 text-[13px] leading-6 text-[var(--mw-muted)]">
            Loading focused node detail...
          </div>
        ) : null}

        <Section title="Conclusion" eyebrow="Core Audit Signal">
          <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
            <div className="text-[15px] leading-7 text-[var(--mw-text)]">
              {keyConclusion || "No conclusion has been recorded for this node."}
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <Metric
                label="Evaluation Score"
                value={typeof detail.evaluation_score === "number" ? detail.evaluation_score.toFixed(2) : "Unavailable"}
                mono
              />
              <Metric label="Operation Type" value={humanize(detail.operation_type)} />
            </div>
          </div>

          <button
            type="button"
            onClick={() => setShowReasoningSummary((current) => !current)}
            className="mt-3 inline-flex items-center gap-2 text-[12px] uppercase tracking-[0.16em] text-[var(--mw-accent)] transition hover:text-[var(--mw-text)]"
          >
            <ChevronDown size={14} className={showReasoningSummary ? "rotate-180 transition" : "transition"} />
            {showReasoningSummary ? "Hide Full Reasoning" : "Show Full Reasoning"}
          </button>

          {showReasoningSummary ? (
            <div className="mt-3 space-y-3">
              <div className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Reasoning Summary</div>
                <div className="mt-2 text-[14px] leading-7 text-[var(--mw-muted)]">
                  {detail.thought_summary || "No reasoning summary was recorded for this node."}
                </div>
              </div>
              {reasoningTrace ? (
                <div className="mw-code-shell rounded-[16px] p-4">
                  <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-[var(--mw-code-comment)]">
                    <span className="h-2.5 w-2.5 rounded-full bg-[var(--mw-danger)]" />
                    <span className="h-2.5 w-2.5 rounded-full bg-[var(--mw-success)]" />
                    <span className="h-2.5 w-2.5 rounded-full bg-[var(--mw-accent)]" />
                    Provider Rationale
                  </div>
                  <pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-[12px] leading-6 text-[var(--mw-code-text)]">
                    {reasoningTrace}
                  </pre>
                </div>
              ) : null}
              {findings.length ? (
                <div className="space-y-2">
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
            </div>
          ) : null}
        </Section>

        <Section title={`Key Evidence (${nodeDetail?.evidence_count ?? detail.evidence_refs.length})`} eyebrow="Grounding">
          <div className="space-y-3">
            {topEvidence.length ? (
              topEvidence.map((reference) => (
                <div key={reference.id} className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[14px] leading-6 text-[var(--mw-text)]">
                        {reference.document_name || reference.document_id}
                      </div>
                      <div className="mt-1 line-clamp-2 text-[13px] leading-6 text-[var(--mw-muted)]">
                        {reference.text_excerpt || reference.chunk_id || "No text excerpt was captured for this evidence reference."}
                      </div>
                    </div>
                    <div className="rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-2.5 py-1 text-[10px] uppercase tracking-[0.14em] text-[var(--mw-accent)]">
                      {humanize(reference.citation_mode || reference.support_level)}
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-3 font-mono text-[11px] text-[var(--mw-subtle)]">
                    <span>{evidenceLocation(reference)}</span>
                    <span>{humanize(reference.support_level)}</span>
                    {reference.retrieval_score !== null ? <span>{reference.retrieval_score.toFixed(3)}</span> : null}
                  </div>
                </div>
              ))
            ) : (
              <div className="text-[14px] leading-7 text-[var(--mw-muted)]">No linked evidence was recorded for this node.</div>
            )}
            {detail.evidence_refs.length > topEvidence.length ? (
              <div className="text-[12px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                Showing top {topEvidence.length} of {detail.evidence_refs.length} evidence items.
              </div>
            ) : null}
          </div>
        </Section>

        <Section title="Execution Mode" eyebrow="Runtime Controls">
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
              <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Executor Type</div>
              <select
                value={executorType}
                onChange={(event) => setExecutorType(event.target.value)}
                className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
              >
                <option value="llm_operator">LLM</option>
                <option value="agent_operator">Agent</option>
                <option value="tool_operator">Tool</option>
                <option value="human_operator">Human</option>
              </select>
            </label>

            <label className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
              <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Executor Profile</div>
              <select
                value={executorProfile}
                onChange={(event) => setExecutorProfile(event.target.value)}
                className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
              >
                <option value="">General</option>
                <option value="forensic">Forensic</option>
                <option value="controls">Controls</option>
                <option value="revenue">Revenue</option>
              </select>
            </label>

            <label className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
              <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Deployed Skill</div>
              <select
                value={selectedSkillId}
                onChange={(event) => setSelectedSkillId(event.target.value)}
                className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
              >
                <option value="">No skill attached</option>
                {availableSkills.map((skill) => (
                  <option key={skill.skill_id} value={skill.skill_id}>
                    {skill.name} · {skill.language}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="mt-3 rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3 text-[13px] leading-6 text-[var(--mw-muted)]">
            {attachedSkill
              ? `Attached skill: ${attachedSkill.name}. It can be invoked from this node during execution and from the live node chat.`
              : "No skill is attached to this node yet. Create and save a skill in the Skills workspace, then deploy it here."}
            <button
              type="button"
              onClick={onOpenSkillsWorkspace}
              className="ml-2 inline-flex items-center gap-1 text-[12px] uppercase tracking-[0.16em] text-[var(--mw-accent)] transition hover:text-[var(--mw-text)]"
            >
              Open Skills Workspace
            </button>
          </div>

          <button
            type="button"
            onClick={() => setShowAdvancedExecution((current) => !current)}
            className="mt-3 inline-flex items-center gap-2 text-[12px] uppercase tracking-[0.16em] text-[var(--mw-accent)] transition hover:text-[var(--mw-text)]"
          >
            <ChevronDown size={14} className={showAdvancedExecution ? "rotate-180 transition" : "transition"} />
            {showAdvancedExecution ? "Hide Advanced Settings" : "Advanced Settings"}
          </button>

          {showAdvancedExecution ? (
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <label className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Max Child Agents</div>
                <input
                  type="number"
                  min={0}
                  value={maxChildAgents}
                  onChange={(event) => setMaxChildAgents(Number(event.target.value))}
                  className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 font-mono text-[14px] text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
                />
              </label>
              <label className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Recursion Depth</div>
                <input
                  type="number"
                  min={0}
                  value={maxRecursionDepth}
                  onChange={(event) => setMaxRecursionDepth(Number(event.target.value))}
                  className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 font-mono text-[14px] text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
                />
              </label>
              <label className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Child Token Budget</div>
                <input
                  type="number"
                  min={0}
                  value={childTokenBudget}
                  onChange={(event) => setChildTokenBudget(Number(event.target.value))}
                  className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 font-mono text-[14px] text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
                />
              </label>
              <label className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3 sm:col-span-3">
                <div className="flex items-center gap-2 text-[12px] uppercase tracking-[0.14em] text-[var(--mw-subtle)]">
                  <input
                    type="checkbox"
                    checked={delegatedSummaryRequired}
                    onChange={(event) => setDelegatedSummaryRequired(event.target.checked)}
                    className="h-4 w-4 accent-[var(--mw-accent)]"
                  />
                  Require child summary return
                </div>
              </label>
            </div>
          ) : null}

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

        <Section title="Node Copilot" eyebrow="Live Agentic Chat">
          <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
            <div className="max-h-[320px] space-y-3 overflow-y-auto pr-1">
              {chatMessages.length ? (
                chatMessages.map((message, index) => (
                  <div
                    key={`${message.role}-${index}`}
                    className={`rounded-[16px] px-4 py-3 ${
                      message.role === "assistant"
                        ? "border border-[var(--mw-border)] bg-[var(--mw-panel)]"
                        : "border border-[var(--mw-accent)] bg-[var(--mw-accent-soft)]"
                    }`}
                  >
                    <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">
                      {message.role === "assistant" ? "Copilot" : "You"}
                    </div>
                    <div className="mt-2 whitespace-pre-wrap text-[14px] leading-7 text-[var(--mw-text)]">{message.content}</div>
                  </div>
                ))
              ) : (
                <div className="rounded-[16px] border border-dashed border-[var(--mw-border)] px-4 py-4 text-[13px] leading-7 text-[var(--mw-muted)]">
                  Ask about this node, request deeper analysis, run its attached skill, or ask for web research when the current evidence is thin.
                </div>
              )}
              {isChatting ? (
                <div className="inline-flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                  <Loader2 size={14} className="animate-spin" />
                  Thinking
                </div>
              ) : null}
            </div>

            {chatResponse?.suggested_actions.length ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {chatResponse.suggested_actions.map((action) => (
                  <button
                    key={action}
                    type="button"
                    onClick={() => void onSendChat(detail.id, action)}
                    className="rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[11px] uppercase tracking-[0.16em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)]"
                  >
                    {action}
                  </button>
                ))}
              </div>
            ) : null}

            {chatResponse?.tool_results.length ? (
              <div className="mt-4 space-y-3">
                <div className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-3 text-[12px] leading-6 text-[var(--mw-muted)]">
                  Used tools: {chatResponse.tool_results.map((result) => String(result.tool ?? result.name ?? "tool")).join(", ")}
                </div>
                {webReferrals.length ? (
                  <div className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-3">
                    <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Linked Online Referrals</div>
                    <div className="mt-3 space-y-2">
                      {webReferrals.map((result) => (
                        <a
                          key={`${result.title}-${result.url}`}
                          href={result.url}
                          target="_blank"
                          rel="noreferrer"
                          className="block rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-3 transition hover:border-[var(--mw-accent)]"
                        >
                          <div className="text-[13px] leading-6 text-[var(--mw-text)]">{result.title}</div>
                          {result.snippet ? (
                            <div className="mt-1 text-[12px] leading-6 text-[var(--mw-muted)]">{result.snippet}</div>
                          ) : null}
                          {result.url ? (
                            <div className="mt-2 font-mono text-[11px] text-[var(--mw-accent)]">{result.url}</div>
                          ) : null}
                        </a>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="mt-4 space-y-3">
            <textarea
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              rows={4}
              className="w-full resize-none rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3 text-[14px] leading-6 text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)] placeholder:text-[var(--mw-subtle)]"
            />
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => void handleSendChat()}
                disabled={isChatting || !chatInput.trim()}
                className="inline-flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Send size={14} />
                {isChatting ? "Working..." : "Send To Copilot"}
              </button>
            </div>
          </div>
        </Section>

        <Section title="Approvals & Compliance" eyebrow="Governance">
          <div className="grid gap-3 sm:grid-cols-2">
            <Metric
              label="Approval State"
              value={
                approvalState
                  ? `${humanize(approvalState.status)} (${approvalState.approved_count}/${approvalState.required_approvals})`
                  : "Not required"
              }
            />
            <Metric label="Delegation" value={`${delegatedChildren.length} child nodes`} mono />
          </div>

          <div className="mt-3 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void onPassAndVerifyNode(detail.id)}
              disabled={isPassing || !nodeCanPass}
              className="rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isPassing ? "Passing..." : "Pass & Verify"}
            </button>
            <div className="max-w-[30rem] text-[12px] leading-5 text-[var(--mw-subtle)]">
              {nodeCanPass
                ? "Manual pass marks the node verified, records any required approvals, and resumes execution when the run is paused."
                : "This node is already completed, verified, and fully approved."}
            </div>
          </div>

          <div className="mt-3 grid gap-3">
            <div className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Approved By</div>
              <div className="mt-2 text-[14px] leading-6 text-[var(--mw-text)]">
                {approvalReviewers.length ? approvalReviewers.join(", ") : "No approvals have been recorded for this node yet."}
              </div>
            </div>

            <div className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Verification Checks</div>
              <div className="mt-2 space-y-2">
                {detail.verification_checks?.length ? (
                  detail.verification_checks.slice(0, 4).map((check) => (
                    <div key={check} className="flex items-start gap-2 text-[13px] leading-6 text-[var(--mw-muted)]">
                      <CheckCircle2 size={14} className="mt-1 shrink-0 text-[var(--mw-success)]" />
                      <span>{check}</span>
                    </div>
                  ))
                ) : (
                  <div className="text-[13px] leading-6 text-[var(--mw-muted)]">No verification checks were recorded for this node.</div>
                )}
              </div>
            </div>

            <div className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Recent Governance Patch</div>
              <div className="mt-2 text-[13px] leading-6 text-[var(--mw-muted)]">
                {lastGovernancePatch
                  ? `${humanize(lastGovernancePatch.patch_type)} · ${lastGovernancePatch.change_reason}`
                  : "No recent governance-relevant patch was recorded for this node."}
              </div>
            </div>
          </div>
        </Section>

        <Section title="Technical Details" eyebrow="">
          <div className="space-y-3">
            <details className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
              <summary className="cursor-pointer text-[12px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">Inputs</summary>
              <pre className="mt-3 overflow-x-auto font-mono text-[11px] leading-6 text-[var(--mw-muted)]">
                {prettyJson(technicalDetails.inputs ?? detail.inputs)}
              </pre>
            </details>
            <details className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
              <summary className="cursor-pointer text-[12px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">Output</summary>
              <pre className="mt-3 overflow-x-auto font-mono text-[11px] leading-6 text-[var(--mw-muted)]">
                {prettyJson(technicalDetails.output ?? detail.output)}
              </pre>
            </details>
            <details className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
              <summary className="cursor-pointer text-[12px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">Model Info</summary>
              <pre className="mt-3 overflow-x-auto font-mono text-[11px] leading-6 text-[var(--mw-muted)]">
                {prettyJson(technicalDetails.model_metadata ?? detail.model_metadata ?? {})}
              </pre>
            </details>
            <details className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
              <summary className="cursor-pointer text-[12px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">Verification Log</summary>
              <pre className="mt-3 overflow-x-auto font-mono text-[11px] leading-6 text-[var(--mw-muted)]">
                {prettyJson(technicalDetails.verification_checks ?? detail.verification_checks ?? [])}
              </pre>
            </details>
            <details className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
              <summary className="cursor-pointer text-[12px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">Patch History</summary>
              <pre className="mt-3 overflow-x-auto font-mono text-[11px] leading-6 text-[var(--mw-muted)]">
                {prettyJson(patchHistory)}
              </pre>
            </details>
            {reasoningTrace ? (
              <details className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                <summary className="cursor-pointer text-[12px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">Provider Rationale</summary>
                <pre className="mt-3 overflow-x-auto whitespace-pre-wrap font-mono text-[11px] leading-6 text-[var(--mw-muted)]">
                  {reasoningTrace}
                </pre>
              </details>
            ) : null}
          </div>
        </Section>
      </div>
    </section>
  );
}
