import { RefreshCcw, Scale, ScrollText, Shuffle, Telescope } from "lucide-react";
import type {
  ReasoningTraceResponse,
  TraceAccessRole,
  ReasoningVisibilityTier,
  RunDiffResponse,
  TaskRunListItem,
  TaskRunResponse,
} from "../types";

interface RunWorkbenchPanelProps {
  task: TaskRunResponse;
  history: TaskRunListItem[];
  offlineDemo: boolean;
  compareTaskId: string;
  traceTier: ReasoningVisibilityTier;
  traceViewerRole: TraceAccessRole;
  traceViewerId: string;
  trace: ReasoningTraceResponse | null;
  diff: RunDiffResponse | null;
  isLoadingTask: boolean;
  isReplaying: boolean;
  isTracing: boolean;
  isDiffing: boolean;
  notice: { tone: "info" | "error"; message: string } | null;
  onSelectTask: (taskId: string) => Promise<void>;
  onReplayTask: () => Promise<void>;
  onCompareTaskChange: (taskId: string) => void;
  onRunDiff: () => Promise<void>;
  onTraceTierChange: (tier: ReasoningVisibilityTier) => void;
  onTraceViewerRoleChange: (role: TraceAccessRole) => void;
  onTraceViewerIdChange: (viewerId: string) => void;
}

function humanize(value: string) {
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function shortHash(value: string | null | undefined) {
  if (!value) {
    return "--";
  }
  return `${value.slice(0, 8)}...${value.slice(-6)}`;
}

function dateLabel(value: string | null | undefined) {
  if (!value) {
    return "Pending";
  }
  return new Date(value).toLocaleString();
}

function formatJsonPreview(value: unknown) {
  if (value == null) {
    return "--";
  }
  return JSON.stringify(value, null, 2);
}

function eventLogFromTask(task: TaskRunResponse) {
  const auditPackage = task.audit_package as { event_log?: Array<Record<string, unknown>> } | null;
  return Array.isArray(auditPackage?.event_log) ? auditPackage.event_log : [];
}

export function RunWorkbenchPanel({
  task,
  history,
  offlineDemo,
  compareTaskId,
  traceTier,
  traceViewerRole,
  traceViewerId,
  trace,
  diff,
  isLoadingTask,
  isReplaying,
  isTracing,
  isDiffing,
  notice,
  onSelectTask,
  onReplayTask,
  onCompareTaskChange,
  onRunDiff,
  onTraceTierChange,
  onTraceViewerRoleChange,
  onTraceViewerIdChange,
}: RunWorkbenchPanelProps) {
  const liveTask = !offlineDemo && task.task_id !== "demo-task";
  const compareCandidates = history.filter((item) => item.task_id !== task.task_id);
  const eventLog = eventLogFromTask(task).slice(-8).reverse();
  const promptTraces = task.prompt_traces ?? [];
  const patchHistory = task.graph_patch_history ?? [];
  const graphVersions = task.graph_version_history ?? [];
  const patchDiffs = task.patch_diff_history ?? [];
  const traceAccessHistory = task.trace_access_history ?? [];
  const evidenceGraphEdges = task.evidence_graph_edges ?? [];
  const evidenceGraphNodeCount = Object.keys(task.evidence_graph_nodes ?? {}).length;

  return (
    <section className="rounded-[22px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-[0.24em] text-[var(--mw-subtle)]">Run Workbench</div>
          <div className="mt-2 font-serif text-[24px] leading-none text-[var(--mw-text)]">Runtime Controls</div>
        </div>
        <div className="rounded-full border border-[var(--mw-border)] px-3 py-1 text-[10px] uppercase tracking-[0.22em] text-[var(--mw-accent)]">
          {liveTask ? humanize(task.status) : "No Active Run"}
        </div>
      </div>

      {notice ? (
        <div
          className={`mt-4 rounded-[16px] border px-3 py-2 text-[13px] leading-6 ${
            notice.tone === "error"
              ? "border-[rgba(190,111,93,0.24)] bg-[rgba(190,111,93,0.10)] text-[var(--mw-text)]"
              : "border-[var(--mw-border)] bg-[var(--mw-node)] text-[var(--mw-muted)]"
          }`}
        >
          {notice.message}
        </div>
      ) : null}

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
          <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--mw-subtle)]">Execution Profile</div>
          <div className="mt-3 space-y-2 text-[13px] leading-6 text-[var(--mw-muted)]">
            <div>Task ID: <span className="font-mono text-[var(--mw-text)]">{task.task_id}</span></div>
            <div>Domain: {task.domain}</div>
            <div>Determinism: {task.determinism_mode ? humanize(task.determinism_mode) : "Unavailable"}</div>
            <div>Control Level: {task.control_level ? humanize(task.control_level) : "Unavailable"}</div>
            <div>Model: {task.model_version || task.model_id || "Unavailable"}</div>
            <div>Provider Fingerprint: <span className="font-mono text-[var(--mw-text)]">{shortHash(task.provider_fingerprint)}</span></div>
            <div>Endpoint: {task.execution_endpoint || "Unavailable"}</div>
            <div>Completed: {dateLabel(task.completed_at)}</div>
          </div>
          <div className="mt-4 grid gap-2">
            <div className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] text-[var(--mw-muted)]">
              Prompt Hash: <span className="font-mono text-[var(--mw-text)]">{shortHash(task.prompt_hash)}</span>
            </div>
            <div className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] text-[var(--mw-muted)]">
              GRS Hash: <span className="font-mono text-[var(--mw-text)]">{shortHash(task.grs_hash)}</span>
            </div>
            <div className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] text-[var(--mw-muted)]">
              Repro Hash: <span className="font-mono text-[var(--mw-text)]">{shortHash(task.reproducibility_hash)}</span>
            </div>
            <div className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] text-[var(--mw-muted)]">
              Env Hash: <span className="font-mono text-[var(--mw-text)]">{shortHash(task.execution_env_hash)}</span>
            </div>
          </div>
        </div>

        <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
          <div className="flex items-center gap-2 text-[var(--mw-accent)]">
            <RefreshCcw size={14} />
            <div className="text-[11px] uppercase tracking-[0.22em]">Replay And Compare</div>
          </div>
          <div className="mt-3 space-y-3">
            <button
              type="button"
              onClick={() => void onReplayTask()}
              disabled={!liveTask || isReplaying}
              className="w-full rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isReplaying ? "Replaying..." : "Replay Current Run"}
            </button>

            <div>
              <div className="mb-2 text-[11px] uppercase tracking-[0.2em] text-[var(--mw-subtle)]">Compare Against</div>
              <select
                value={compareTaskId}
                onChange={(event) => onCompareTaskChange(event.target.value)}
                className="w-full rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[13px] text-[var(--mw-text)] outline-none"
              >
                <option value="">Select a prior run</option>
                {compareCandidates.map((item) => (
                  <option key={item.task_id} value={item.task_id}>
                    {item.task_id} · {humanize(item.status)} · {humanize(item.determinism_mode ?? "unknown")}
                  </option>
                ))}
              </select>
            </div>

            <button
              type="button"
              onClick={() => void onRunDiff()}
              disabled={!liveTask || !compareTaskId || isDiffing}
              className="w-full rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isDiffing ? "Comparing..." : "Run Diff"}
            </button>
          </div>
        </div>
      </div>

      <div className="mt-4 rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-[var(--mw-accent)]">
            <Telescope size={14} />
            <div className="text-[11px] uppercase tracking-[0.22em]">Reasoning Trace</div>
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            <select
              value={traceTier}
              onChange={(event) => onTraceTierChange(event.target.value as ReasoningVisibilityTier)}
              className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] text-[var(--mw-text)] outline-none"
            >
              <option value="summary_trace">Summary Trace</option>
              <option value="structured_reasoning_trace">Structured Trace</option>
              <option value="expanded_analytic_trace">Expanded Trace</option>
            </select>
            <select
              value={traceViewerRole}
              onChange={(event) => onTraceViewerRoleChange(event.target.value as TraceAccessRole)}
              className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] text-[var(--mw-text)] outline-none"
            >
              <option value="viewer">Viewer</option>
              <option value="reviewer">Reviewer</option>
              <option value="auditor">Auditor</option>
              <option value="admin">Admin</option>
            </select>
            <input
              value={traceViewerId}
              onChange={(event) => onTraceViewerIdChange(event.target.value)}
              placeholder="viewer id"
              className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] text-[var(--mw-text)] outline-none placeholder:text-[var(--mw-subtle)]"
            />
          </div>
        </div>
        {trace?.metadata ? (
          <div className="mt-3 rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] leading-6 text-[var(--mw-muted)]">
            Requested: {humanize(String(trace.metadata.requested_tier ?? traceTier))} · Effective:{" "}
            {humanize(String(trace.metadata.effective_tier ?? trace.tier))} · Viewer: {String(trace.metadata.viewer_id ?? traceViewerId)} ·{" "}
            Accesses: {String(trace.metadata.access_count ?? traceAccessHistory.length)}
          </div>
        ) : null}
        <div className="mt-3 max-h-[340px] space-y-2 overflow-y-auto">
          {isTracing ? (
            <div className="text-[13px] leading-6 text-[var(--mw-muted)]">Loading reasoning trace...</div>
          ) : trace?.entries?.length ? (
            trace.entries.map((entry) => (
              <div key={entry.node_id} className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="font-serif text-[16px] text-[var(--mw-text)]">{entry.title}</div>
                  <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--mw-subtle)]">{humanize(entry.status)}</div>
                </div>
                <div className="mt-1 text-[13px] leading-6 text-[var(--mw-muted)]">{entry.conclusion}</div>
                <div className="mt-2 text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                  Evidence {entry.evidence_used.length}
                  {entry.verification_status ? ` · ${humanize(entry.verification_status)}` : ""}
                  {typeof entry.score === "number" ? ` · Score ${entry.score.toFixed(2)}` : ""}
                </div>
                {entry.prompt_hash ? (
                  <div className="mt-2 text-[12px] text-[var(--mw-muted)]">
                    Prompt Hash: <span className="font-mono text-[var(--mw-text)]">{shortHash(entry.prompt_hash)}</span>
                  </div>
                ) : null}
                {entry.evidence_used.length ? (
                  <div className="mt-2 space-y-1">
                    {entry.evidence_used.slice(0, 2).map((reference) => (
                      <div key={reference.id} className="text-[12px] leading-6 text-[var(--mw-muted)]">
                        {reference.document_name} · {reference.chunk_id} · {humanize(reference.support_level)}
                      </div>
                    ))}
                  </div>
                ) : null}
                {entry.claims?.length ? (
                  <div className="mt-2 space-y-1">
                    {entry.claims.slice(0, 3).map((claim) => (
                      <div key={claim.id} className="rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[12px] leading-6 text-[var(--mw-muted)]">
                        <span className="text-[var(--mw-text)]">{claim.text}</span>
                        <br />
                        {humanize(claim.claim_classification)} · {humanize(claim.support_level)} · {claim.evidence_refs.length} evidence links
                      </div>
                    ))}
                  </div>
                ) : null}
                {entry.output ? (
                  <pre className="mt-2 overflow-x-auto rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[11px] leading-6 text-[var(--mw-muted)]">
                    {formatJsonPreview(entry.output)}
                  </pre>
                ) : null}
                {entry.thought_summary ? (
                  <div className="mt-2 text-[12px] leading-6 text-[var(--mw-muted)]">{entry.thought_summary}</div>
                ) : null}
                {entry.expansion_contracts?.length ? (
                  <div className="mt-2 text-[11px] uppercase tracking-[0.14em] text-[var(--mw-subtle)]">
                    {entry.expansion_contracts.map(humanize).join(" · ")}
                  </div>
                ) : null}
              </div>
            ))
          ) : (
            <div className="text-[13px] leading-6 text-[var(--mw-muted)]">
              {liveTask ? "No reasoning trace entries are available yet." : "Execute or load a run to inspect its reasoning trace."}
            </div>
          )}
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
          <div className="flex items-center gap-2 text-[var(--mw-accent)]">
            <Shuffle size={14} />
            <div className="text-[11px] uppercase tracking-[0.22em]">Diff Results</div>
          </div>
          {diff ? (
            <div className="mt-3 space-y-3">
              <div className="grid gap-2 sm:grid-cols-4">
                <div className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] text-[var(--mw-muted)]">
                  Nodes<br />
                  <span className="font-serif text-[22px] text-[var(--mw-text)]">{diff.changed_nodes.length}</span>
                </div>
                <div className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] text-[var(--mw-muted)]">
                  Prompts<br />
                  <span className="font-serif text-[22px] text-[var(--mw-text)]">{diff.changed_prompts.length}</span>
                </div>
                <div className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] text-[var(--mw-muted)]">
                  Evidence<br />
                  <span className="font-serif text-[22px] text-[var(--mw-text)]">{diff.changed_evidence.length}</span>
                </div>
                <div className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] text-[var(--mw-muted)]">
                  Final Output<br />
                  <span className="font-serif text-[22px] text-[var(--mw-text)]">
                    {diff.changed_final_output.changed ? "Yes" : "No"}
                  </span>
                </div>
              </div>
              <div className="max-h-[220px] space-y-2 overflow-y-auto">
                {diff.changed_nodes.length ? (
                  diff.changed_nodes.map((entry) => (
                    <div key={entry.node_id} className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[13px] leading-6 text-[var(--mw-muted)]">
                      <div className="font-serif text-[15px] text-[var(--mw-text)]">{humanize(entry.node_id)}</div>
                      <div className="mt-1">Changed: {entry.changed_fields.map(humanize).join(", ")}</div>
                    </div>
                  ))
                ) : (
                  <div className="text-[13px] leading-6 text-[var(--mw-muted)]">No node-level differences detected.</div>
                )}
              </div>
              <div className="grid gap-3 xl:grid-cols-2">
                <div className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-3">
                  <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">Prompt Changes</div>
                  <div className="mt-2 max-h-[160px] space-y-2 overflow-y-auto">
                    {diff.changed_prompts.length ? (
                      diff.changed_prompts.map((entry, index) => (
                        <div key={`${entry.phase}-${entry.node_id ?? "graph"}-${index}`} className="text-[12px] leading-6 text-[var(--mw-muted)]">
                          {humanize(entry.phase)}{entry.node_id ? ` · ${humanize(entry.node_id)}` : ""}<br />
                          <span className="font-mono text-[var(--mw-text)]">{shortHash(entry.left_prompt_hash)}</span> {"->"}{" "}
                          <span className="font-mono text-[var(--mw-text)]">{shortHash(entry.right_prompt_hash)}</span>
                        </div>
                      ))
                    ) : (
                      <div className="text-[12px] leading-6 text-[var(--mw-muted)]">No prompt differences detected.</div>
                    )}
                  </div>
                </div>
                <div className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-3">
                  <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">Evidence Changes</div>
                  <div className="mt-2 max-h-[160px] space-y-2 overflow-y-auto">
                    {diff.changed_evidence.length ? (
                      diff.changed_evidence.map((entry) => (
                        <div key={entry.node_id} className="text-[12px] leading-6 text-[var(--mw-muted)]">
                          {humanize(entry.node_id)}<br />
                          <span className="font-mono text-[var(--mw-text)]">{entry.left_evidence_ids.length}</span> {"->"}{" "}
                          <span className="font-mono text-[var(--mw-text)]">{entry.right_evidence_ids.length}</span> evidence links
                        </div>
                      ))
                    ) : (
                      <div className="text-[12px] leading-6 text-[var(--mw-muted)]">No evidence differences detected.</div>
                    )}
                  </div>
                </div>
              </div>
              <div className="grid gap-3 xl:grid-cols-2">
                <div className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-3">
                  <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">Model Metadata</div>
                  <pre className="mt-2 overflow-x-auto text-[11px] leading-6 text-[var(--mw-muted)]">
                    {formatJsonPreview(diff.changed_model_metadata)}
                  </pre>
                </div>
                <div className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-3">
                  <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">Final Output</div>
                  <pre className="mt-2 overflow-x-auto text-[11px] leading-6 text-[var(--mw-muted)]">
                    {formatJsonPreview(diff.changed_final_output)}
                  </pre>
                </div>
              </div>
            </div>
          ) : (
            <div className="mt-3 text-[13px] leading-6 text-[var(--mw-muted)]">
              Select another run and execute a diff to compare prompts, node outputs, evidence, and final output.
            </div>
          )}
        </div>

        <div className="space-y-4">
          <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-[var(--mw-accent)]">
                <Scale size={14} />
                <div className="text-[11px] uppercase tracking-[0.22em]">Recent Runs</div>
              </div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                {task.execution_sequence?.length ?? 0} executed nodes
              </div>
            </div>
            <div className="mt-3 max-h-[220px] space-y-2 overflow-y-auto">
              {history.length ? (
                history.map((item) => (
                  <button
                    key={item.task_id}
                    type="button"
                    onClick={() => void onSelectTask(item.task_id)}
                    disabled={isLoadingTask}
                    className={`w-full rounded-[14px] border px-3 py-2 text-left transition ${
                      item.task_id === task.task_id
                        ? "border-[var(--mw-accent)] bg-[var(--mw-accent-soft)]"
                        : "border-[var(--mw-border)] bg-[var(--mw-panel)] hover:border-[var(--mw-accent)]"
                    }`}
                  >
                    <div className="font-mono text-[12px] text-[var(--mw-text)]">{item.task_id}</div>
                    <div className="mt-1 text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                      {humanize(item.status)} · {humanize(item.determinism_mode ?? "unknown")}
                    </div>
                  </button>
                ))
              ) : (
                <div className="text-[13px] leading-6 text-[var(--mw-muted)]">No persisted runs are available yet.</div>
              )}
            </div>
          </div>

          <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
            <div className="flex items-center gap-2 text-[var(--mw-accent)]">
              <ScrollText size={14} />
              <div className="text-[11px] uppercase tracking-[0.22em]">Audit Stream</div>
            </div>
            <div className="mt-3 max-h-[220px] space-y-2 overflow-y-auto">
              {eventLog.length ? (
                eventLog.map((entry, index) => (
                  <div key={`${String(entry.timestamp)}-${index}`} className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2">
                    <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                      {humanize(String(entry.event ?? "event"))}
                    </div>
                    <div className="mt-1 text-[13px] leading-6 text-[var(--mw-muted)]">{String(entry.message ?? "")}</div>
                  </div>
                ))
              ) : (
                <div className="text-[13px] leading-6 text-[var(--mw-muted)]">No audit events are available for the current task.</div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1fr]">
        <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
          <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--mw-subtle)]">Prompt Trace Ledger</div>
          <div className="mt-3 max-h-[220px] space-y-2 overflow-y-auto">
            {promptTraces.length ? (
              promptTraces.map((trace) => (
                <div key={trace.trace_id} className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2">
                  <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                    {humanize(trace.phase)}{trace.node_id ? ` · ${humanize(trace.node_id)}` : ""}
                  </div>
                  <div className="mt-1 text-[13px] leading-6 text-[var(--mw-muted)]">{trace.model_version || trace.model_id}</div>
                  <div className="mt-1 text-[12px] leading-6 text-[var(--mw-muted)]">
                    {shortHash(trace.prompt_hash)} · {shortHash(trace.response_hash)}
                  </div>
                </div>
              ))
            ) : (
              <div className="text-[13px] leading-6 text-[var(--mw-muted)]">No prompt traces are stored for the current task.</div>
            )}
          </div>
        </div>

        <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
          <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--mw-subtle)]">Graph Patch And Evidence</div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-3 text-[12px] text-[var(--mw-muted)]">
              Evidence Nodes<br />
              <span className="font-serif text-[24px] text-[var(--mw-text)]">{evidenceGraphNodeCount}</span>
            </div>
            <div className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-3 text-[12px] text-[var(--mw-muted)]">
              Evidence Edges<br />
              <span className="font-serif text-[24px] text-[var(--mw-text)]">{evidenceGraphEdges.length}</span>
            </div>
          </div>
          <div className="mt-3 max-h-[150px] space-y-2 overflow-y-auto">
            {patchHistory.length ? (
              patchHistory.map((patch) => (
                <div key={patch.patch_id} className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] leading-6 text-[var(--mw-muted)]">
                  {humanize(patch.patch_type)}{patch.target_node_id ? ` · ${humanize(patch.target_node_id)}` : ""}<br />
                  {patch.change_reason}
                </div>
              ))
            ) : (
              <div className="text-[13px] leading-6 text-[var(--mw-muted)]">No graph patches were applied to this task.</div>
            )}
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1fr_1fr]">
        <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
          <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--mw-subtle)]">Graph Versions</div>
          <div className="mt-3 max-h-[200px] space-y-2 overflow-y-auto">
            {graphVersions.length ? (
              graphVersions.map((version) => (
                <div key={version.version_id} className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] leading-6 text-[var(--mw-muted)]">
                  <span className="font-mono text-[var(--mw-text)]">{version.program_version}</span>
                  <br />
                  {version.reason}
                  <br />
                  By {version.created_by} · {dateLabel(version.created_at)}
                </div>
              ))
            ) : (
              <div className="text-[13px] leading-6 text-[var(--mw-muted)]">No graph versions are recorded yet.</div>
            )}
          </div>
        </div>

        <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
          <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--mw-subtle)]">Patch Diffs</div>
          <div className="mt-3 max-h-[200px] space-y-2 overflow-y-auto">
            {patchDiffs.length ? (
              patchDiffs.map((diffEntry) => (
                <div key={diffEntry.patch_id} className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] leading-6 text-[var(--mw-muted)]">
                  {humanize(diffEntry.patch_type)} · {diffEntry.before_program_version} {"->"} {diffEntry.after_program_version}
                  <br />
                  Nodes +{diffEntry.added_nodes.length} / -{diffEntry.removed_nodes.length} / ~{diffEntry.changed_nodes.length}
                  <br />
                  Policy {diffEntry.changed_policy ? "changed" : "unchanged"} · Budget {diffEntry.changed_budget ? "changed" : "unchanged"}
                </div>
              ))
            ) : (
              <div className="text-[13px] leading-6 text-[var(--mw-muted)]">No patch diffs are available for this task.</div>
            )}
          </div>
        </div>

        <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
          <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--mw-subtle)]">Trace Access Log</div>
          <div className="mt-3 max-h-[200px] space-y-2 overflow-y-auto">
            {traceAccessHistory.length ? (
              traceAccessHistory
                .slice()
                .reverse()
                .slice(0, 8)
                .map((access, index) => (
                  <div key={`${access.viewer_id}-${access.accessed_at}-${index}`} className="rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[12px] leading-6 text-[var(--mw-muted)]">
                    {access.viewer_id} · {humanize(access.viewer_role)}
                    <br />
                    {humanize(access.requested_tier)} {"->"} {humanize(access.effective_tier)}
                    <br />
                    {access.entry_count} entries · {dateLabel(access.accessed_at)}
                  </div>
                ))
            ) : (
              <div className="text-[13px] leading-6 text-[var(--mw-muted)]">No reasoning trace views have been logged yet.</div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
