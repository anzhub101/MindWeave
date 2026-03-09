import type { ReactNode } from "react";
import {
  ArrowRight,
  Clock3,
  FileCode2,
  FileSearch,
  Fingerprint,
  GitBranchPlus,
  LayoutDashboard,
  Orbit,
  ScrollText,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import type {
  ControlLevel,
  DeterminismMode,
  TaskRunListItem,
  TaskRunResponse,
  TemplateSummary,
} from "../types";

interface OperationsViewProps {
  activeItem: string;
  task: TaskRunResponse;
  history: TaskRunListItem[];
  templates: TemplateSummary[];
  offlineDemo: boolean;
  isLoadingTask: boolean;
  isLoadingTemplates: boolean;
  isReplayingTask: boolean;
  notice: { tone: "info" | "error"; message: string } | null;
  determinismMode: DeterminismMode;
  controlLevel: ControlLevel;
  autoApproveHumanReview: boolean;
  onDeterminismModeChange: (value: DeterminismMode) => void;
  onControlLevelChange: (value: ControlLevel) => void;
  onAutoApproveHumanReviewChange: (value: boolean) => void;
  onSelectTask: (taskId: string) => Promise<void>;
  onReplayTask: () => Promise<void>;
  onNavigateReasoning: () => void;
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

function prettyJson(value: unknown) {
  return JSON.stringify(value, null, 2);
}

function eventLogFromTask(task: TaskRunResponse) {
  const auditPackage = task.audit_package as { event_log?: Array<Record<string, unknown>> } | null;
  return Array.isArray(auditPackage?.event_log) ? auditPackage.event_log : [];
}

function Panel({
  title,
  eyebrow,
  icon: Icon,
  children,
}: {
  title: string;
  eyebrow: string;
  icon: typeof LayoutDashboard;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[24px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-5">
      <div className="flex items-start gap-3">
        <div className="mt-1 rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] p-2 text-[var(--mw-accent)]">
          <Icon size={16} />
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-[0.24em] text-[var(--mw-subtle)]">{eyebrow}</div>
          <div className="mt-1 font-serif text-[24px] leading-none text-[var(--mw-text)]">{title}</div>
        </div>
      </div>
      <div className="mt-5">{children}</div>
    </section>
  );
}

function EmptyState({
  title,
  body,
  actionLabel,
  onAction,
}: {
  title: string;
  body: string;
  actionLabel: string;
  onAction: () => void;
}) {
  return (
    <div className="rounded-[20px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-6">
      <div className="font-serif text-[24px] text-[var(--mw-text)]">{title}</div>
      <div className="mt-2 max-w-2xl text-[14px] leading-7 text-[var(--mw-muted)]">{body}</div>
      <button
        type="button"
        onClick={onAction}
        className="mt-5 inline-flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)]"
      >
        {actionLabel}
        <ArrowRight size={14} />
      </button>
    </div>
  );
}

function RuntimeNotice({ notice }: { notice: OperationsViewProps["notice"] }) {
  if (!notice) {
    return null;
  }
  return (
    <div
      className={`rounded-[18px] border px-4 py-3 text-[13px] leading-6 ${
        notice.tone === "error"
          ? "border-[rgba(190,111,93,0.28)] bg-[rgba(190,111,93,0.10)] text-[var(--mw-text)]"
          : "border-[var(--mw-border)] bg-[var(--mw-node)] text-[var(--mw-muted)]"
      }`}
    >
      {notice.message}
    </div>
  );
}

function DashboardView({
  task,
  history,
  offlineDemo,
  notice,
  onSelectTask,
  onNavigateReasoning,
}: Pick<
  OperationsViewProps,
  "task" | "history" | "offlineDemo" | "notice" | "onSelectTask" | "onNavigateReasoning"
>) {
  const evidenceNodeCount = Object.keys(task.evidence_graph_nodes ?? {}).length;
  const promptTraceCount = task.prompt_traces?.length ?? 0;
  const patchCount = task.graph_patch_history?.length ?? 0;
  const eventLog = eventLogFromTask(task).slice(-5).reverse();
  const recentRuns = history.slice(0, 6);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4 pt-4">
      <RuntimeNotice notice={notice} />

      <Panel title="System Overview" eyebrow="Runtime Status" icon={LayoutDashboard}>
        <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
          <div>
            <div className="text-[13px] leading-7 text-[var(--mw-muted)]">
              {offlineDemo
                ? "The workspace is showing demo data. Execute a live run in the reasoning view to populate replay, diff, trace, and audit controls with persisted backend state."
                : "The active run is fully traceable: deterministic metadata, evidence graph, prompt traces, patch history, and audit logs are available from the current task record."}
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Nodes</div>
                <div className="mt-3 font-serif text-[34px] leading-none text-[var(--mw-text)]">{task.nodes.length}</div>
              </div>
              <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Evidence Graph</div>
                <div className="mt-3 font-serif text-[34px] leading-none text-[var(--mw-text)]">{evidenceNodeCount}</div>
              </div>
              <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Prompt Traces</div>
                <div className="mt-3 font-serif text-[34px] leading-none text-[var(--mw-text)]">{promptTraceCount}</div>
              </div>
              <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Graph Patches</div>
                <div className="mt-3 font-serif text-[34px] leading-none text-[var(--mw-text)]">{patchCount}</div>
              </div>
            </div>
            <button
              type="button"
              onClick={onNavigateReasoning}
              className="mt-5 inline-flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)]"
            >
              Open Reasoning Workspace
              <Orbit size={14} />
            </button>
          </div>

          <div className="rounded-[20px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
            <div className="flex items-center gap-2 text-[var(--mw-accent)]">
              <Fingerprint size={14} />
              <div className="text-[11px] uppercase tracking-[0.22em]">Execution Profile</div>
            </div>
            <div className="mt-3 space-y-2 text-[13px] leading-6 text-[var(--mw-muted)]">
              <div>Task ID: <span className="font-mono text-[var(--mw-text)]">{task.task_id}</span></div>
              <div>Determinism: {humanize(task.determinism_mode ?? "unknown")}</div>
              <div>Control Level: {humanize(task.control_level ?? "unknown")}</div>
              <div>Model: {task.model_version || task.model_id || "Unavailable"}</div>
              <div>Provider Fingerprint: <span className="font-mono text-[var(--mw-text)]">{shortHash(task.provider_fingerprint)}</span></div>
              <div>Prompt Hash: <span className="font-mono text-[var(--mw-text)]">{shortHash(task.prompt_hash)}</span></div>
              <div>Reproducibility Hash: <span className="font-mono text-[var(--mw-text)]">{shortHash(task.reproducibility_hash)}</span></div>
            </div>
          </div>
        </div>
      </Panel>

      <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <Panel title="Recent Runs" eyebrow="Task History" icon={Clock3}>
          <div className="space-y-2">
            {recentRuns.length ? (
              recentRuns.map((item) => (
                <button
                  key={item.task_id}
                  type="button"
                  onClick={() => void onSelectTask(item.task_id)}
                  className={`w-full rounded-[18px] border px-4 py-3 text-left transition ${
                    item.task_id === task.task_id
                      ? "border-[var(--mw-accent)] bg-[var(--mw-accent-soft)]"
                      : "border-[var(--mw-border)] bg-[var(--mw-node)] hover:border-[var(--mw-accent)]"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-mono text-[12px] text-[var(--mw-text)]">{item.task_id}</div>
                      <div className="mt-1 text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                        {humanize(item.status)} · {humanize(item.determinism_mode ?? "unknown")} · {humanize(item.control_level ?? "unknown")}
                      </div>
                    </div>
                    <div className="text-[12px] text-[var(--mw-muted)]">{dateLabel(item.completed_at ?? item.created_at)}</div>
                  </div>
                </button>
              ))
            ) : (
              <div className="text-[14px] leading-7 text-[var(--mw-muted)]">No task history is available yet.</div>
            )}
          </div>
        </Panel>

        <Panel title="Latest Audit Events" eyebrow="Event Stream" icon={ScrollText}>
          <div className="space-y-2">
            {eventLog.length ? (
              eventLog.map((entry, index) => (
                <div key={`${String(entry.timestamp)}-${index}`} className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                  <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                    {humanize(String(entry.event ?? "event"))}
                  </div>
                  <div className="mt-1 text-[13px] leading-6 text-[var(--mw-muted)]">{String(entry.message ?? "")}</div>
                </div>
              ))
            ) : (
              <div className="text-[14px] leading-7 text-[var(--mw-muted)]">No audit events were recorded for the current task.</div>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function HistoryView({
  task,
  history,
  isLoadingTask,
  isReplayingTask,
  notice,
  onSelectTask,
  onReplayTask,
}: Pick<
  OperationsViewProps,
  "task" | "history" | "isLoadingTask" | "isReplayingTask" | "notice" | "onSelectTask" | "onReplayTask"
>) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4 pt-4">
      <RuntimeNotice notice={notice} />
      <Panel title="Run History" eyebrow="Persisted Tasks" icon={Clock3}>
        <div className="flex items-center justify-between gap-3">
          <div className="text-[13px] leading-7 text-[var(--mw-muted)]">
            Load any persisted run back into the workspace, or replay the current run with its saved program and determinism settings.
          </div>
          <button
            type="button"
            onClick={() => void onReplayTask()}
            disabled={isReplayingTask}
            className="rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isReplayingTask ? "Replaying..." : "Replay Current Run"}
          </button>
        </div>
        <div className="mt-4 space-y-3">
          {history.length ? (
            history.map((item) => (
              <div
                key={item.task_id}
                className={`rounded-[20px] border px-4 py-4 ${
                  item.task_id === task.task_id
                    ? "border-[var(--mw-accent)] bg-[var(--mw-accent-soft)]"
                    : "border-[var(--mw-border)] bg-[var(--mw-node)]"
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="max-w-3xl">
                    <div className="font-mono text-[12px] text-[var(--mw-text)]">{item.task_id}</div>
                    <div className="mt-1 text-[11px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">
                      {humanize(item.status)} · {humanize(item.determinism_mode ?? "unknown")} · {humanize(item.control_level ?? "unknown")}
                    </div>
                    <div className="mt-3 text-[14px] leading-7 text-[var(--mw-muted)]">{item.prompt}</div>
                    {item.final_summary?.headline ? (
                      <div className="mt-3 text-[13px] leading-6 text-[var(--mw-text)]">{item.final_summary.headline}</div>
                    ) : null}
                  </div>
                  <div className="flex flex-col items-end gap-3">
                    <div className="text-[12px] text-[var(--mw-muted)]">{dateLabel(item.completed_at ?? item.created_at)}</div>
                    <button
                      type="button"
                      onClick={() => void onSelectTask(item.task_id)}
                      disabled={isLoadingTask || item.task_id === task.task_id}
                      className="rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {item.task_id === task.task_id ? "Current Run" : isLoadingTask ? "Loading..." : "Open Run"}
                    </button>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className="text-[14px] leading-7 text-[var(--mw-muted)]">No persisted tasks are available yet.</div>
          )}
        </div>
      </Panel>
    </div>
  );
}

function AuditView({ task, notice }: Pick<OperationsViewProps, "task" | "notice">) {
  const eventLog = eventLogFromTask(task).slice().reverse();
  const promptTraces = task.prompt_traces ?? [];
  const patchHistory = task.graph_patch_history ?? [];
  const graphVersions = task.graph_version_history ?? [];
  const patchDiffs = task.patch_diff_history ?? [];
  const traceAccessHistory = task.trace_access_history ?? [];
  const schemaLogs = task.schema_validation_logs ?? [];
  const evidenceEdges = task.evidence_graph_edges ?? [];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4 pt-4">
      <RuntimeNotice notice={notice} />
      <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <Panel title="Prompt Traces" eyebrow="LLM Audit Trail" icon={FileCode2}>
          <div className="space-y-3">
            {promptTraces.length ? (
              promptTraces.map((trace) => (
                <div key={trace.trace_id} className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">
                        {humanize(trace.phase)}{trace.node_id ? ` · ${humanize(trace.node_id)}` : ""}
                      </div>
                      <div className="mt-1 font-serif text-[18px] text-[var(--mw-text)]">
                        {trace.model_version || trace.model_id}
                      </div>
                    </div>
                    <div className="text-[12px] text-[var(--mw-muted)]">{dateLabel(trace.created_at)}</div>
                  </div>
                  <div className="mt-3 grid gap-2 text-[12px] leading-6 text-[var(--mw-muted)]">
                    <div>Provider Fingerprint: <span className="font-mono text-[var(--mw-text)]">{shortHash(trace.provider_fingerprint)}</span></div>
                    <div>Prompt Hash: <span className="font-mono text-[var(--mw-text)]">{shortHash(trace.prompt_hash)}</span></div>
                    <div>Response Hash: <span className="font-mono text-[var(--mw-text)]">{shortHash(trace.response_hash)}</span></div>
                  </div>
                  <div className="mt-3 grid gap-3 xl:grid-cols-2">
                    <pre className="overflow-x-auto rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-3 text-[11px] leading-6 text-[var(--mw-muted)]">{prettyJson(trace.params)}</pre>
                    <pre className="overflow-x-auto rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-3 text-[11px] leading-6 text-[var(--mw-muted)]">{prettyJson(trace.context)}</pre>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-[14px] leading-7 text-[var(--mw-muted)]">No prompt traces are available for the current task.</div>
            )}
          </div>
        </Panel>

        <Panel title="Audit Events" eyebrow="Execution Log" icon={ScrollText}>
          <div className="space-y-2">
            {eventLog.length ? (
              eventLog.map((entry, index) => (
                <div key={`${String(entry.timestamp)}-${index}`} className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                  <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                    {humanize(String(entry.event ?? "event"))}
                  </div>
                  <div className="mt-1 text-[13px] leading-6 text-[var(--mw-muted)]">{String(entry.message ?? "")}</div>
                </div>
              ))
            ) : (
              <div className="text-[14px] leading-7 text-[var(--mw-muted)]">No audit events were recorded.</div>
            )}
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
        <Panel title="Evidence Graph" eyebrow="Claim To Source Mapping" icon={FileSearch}>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
              <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Graph Nodes</div>
              <div className="mt-3 font-serif text-[30px] leading-none text-[var(--mw-text)]">
                {Object.keys(task.evidence_graph_nodes ?? {}).length}
              </div>
            </div>
            <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
              <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Graph Edges</div>
              <div className="mt-3 font-serif text-[30px] leading-none text-[var(--mw-text)]">{evidenceEdges.length}</div>
            </div>
          </div>
          <div className="mt-4 space-y-2">
            {evidenceEdges.length ? (
              evidenceEdges.map((edge, index) => (
                <div key={`${edge.source}-${edge.target}-${index}`} className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                  <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">{humanize(edge.relation)}</div>
                  <div className="mt-1 text-[13px] leading-6 text-[var(--mw-muted)]">
                    <span className="font-mono text-[var(--mw-text)]">{edge.source}</span> {"->"} <span className="font-mono text-[var(--mw-text)]">{edge.target}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-[14px] leading-7 text-[var(--mw-muted)]">No evidence graph edges are available.</div>
            )}
          </div>
        </Panel>

        <div className="grid gap-4">
          <Panel title="Patch History" eyebrow="Graph Changes" icon={GitBranchPlus}>
            <div className="space-y-2">
              {patchHistory.length ? (
                patchHistory.map((patch) => (
                  <div key={patch.patch_id} className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                    <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                      {humanize(patch.patch_type)}{patch.target_node_id ? ` · ${humanize(patch.target_node_id)}` : ""}
                    </div>
                    <div className="mt-1 text-[13px] leading-6 text-[var(--mw-muted)]">{patch.change_reason}</div>
                  </div>
                ))
              ) : (
                <div className="text-[14px] leading-7 text-[var(--mw-muted)]">No graph patches were applied to this run.</div>
              )}
            </div>
          </Panel>

          <Panel title="Graph Versions" eyebrow="Version Lineage" icon={GitBranchPlus}>
            <div className="space-y-2">
              {graphVersions.length ? (
                graphVersions.map((version) => (
                  <div key={version.version_id} className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                    <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                      {version.program_version}
                    </div>
                    <div className="mt-1 text-[13px] leading-6 text-[var(--mw-muted)]">
                      {version.reason}<br />
                      By {version.created_by} · {dateLabel(version.created_at)}
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-[14px] leading-7 text-[var(--mw-muted)]">No graph versions are available.</div>
              )}
            </div>
          </Panel>

          <Panel title="Patch Diffs" eyebrow="Change Artifacts" icon={GitBranchPlus}>
            <div className="space-y-2">
              {patchDiffs.length ? (
                patchDiffs.map((entry) => (
                  <div key={entry.patch_id} className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                    <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                      {humanize(entry.patch_type)} · {entry.before_program_version} {"->"} {entry.after_program_version}
                    </div>
                    <div className="mt-1 text-[13px] leading-6 text-[var(--mw-muted)]">
                      Added nodes: {entry.added_nodes.length} · Removed nodes: {entry.removed_nodes.length} · Changed nodes: {entry.changed_nodes.length}
                      <br />
                      Policy changed: {entry.changed_policy ? "Yes" : "No"} · Budget changed: {entry.changed_budget ? "Yes" : "No"}
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-[14px] leading-7 text-[var(--mw-muted)]">No patch diffs are available.</div>
              )}
            </div>
          </Panel>

          <Panel title="Trace Access" eyebrow="Reasoning View Log" icon={ScrollText}>
            <div className="space-y-2">
              {traceAccessHistory.length ? (
                traceAccessHistory
                  .slice()
                  .reverse()
                  .map((entry, index) => (
                    <div key={`${entry.viewer_id}-${entry.accessed_at}-${index}`} className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                      <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                        {humanize(entry.viewer_role)} · {entry.viewer_id}
                      </div>
                      <div className="mt-1 text-[13px] leading-6 text-[var(--mw-muted)]">
                        {humanize(entry.requested_tier)} {"->"} {humanize(entry.effective_tier)} · {entry.entry_count} entries
                        <br />
                        {dateLabel(entry.accessed_at)}
                      </div>
                    </div>
                  ))
              ) : (
                <div className="text-[14px] leading-7 text-[var(--mw-muted)]">No trace access events are available.</div>
              )}
            </div>
          </Panel>

          <Panel title="Schema Validation" eyebrow="Output Controls" icon={ShieldCheck}>
            <div className="space-y-2">
              {schemaLogs.length ? (
                schemaLogs.map((entry, index) => (
                  <div key={`${entry.node_id}-${entry.schema_id}-${index}`} className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3">
                    <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                      {humanize(entry.phase)} · {humanize(entry.node_id)}
                    </div>
                    <div className="mt-1 text-[13px] leading-6 text-[var(--mw-muted)]">{entry.message || (entry.passed ? "Validation passed." : "Validation failed.")}</div>
                  </div>
                ))
              ) : (
                <div className="text-[14px] leading-7 text-[var(--mw-muted)]">No schema validation logs are available.</div>
              )}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function TemplatesView({
  task,
  templates,
  isLoadingTemplates,
  onNavigateReasoning,
}: Pick<OperationsViewProps, "task" | "templates" | "isLoadingTemplates" | "onNavigateReasoning">) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4 pt-4">
      <Panel title="Program Templates" eyebrow="Design Plane" icon={FileCode2}>
        <div className="text-[13px] leading-7 text-[var(--mw-muted)]">
          Templates and synthesized programs are backend-managed artifacts. The runtime currently executes the program attached to the task record; this page exposes the available templates and the active program lineage.
        </div>
        <div className="mt-5 grid gap-3 xl:grid-cols-2">
          <div className="rounded-[20px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
            <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Active Program</div>
            <div className="mt-3 font-serif text-[22px] text-[var(--mw-text)]">{task.program_id}</div>
            <div className="mt-2 text-[13px] leading-6 text-[var(--mw-muted)]">
              Template: {task.template_id}<br />
              Version: {task.program_version}<br />
              Domain: {task.domain}
            </div>
            <button
              type="button"
              onClick={onNavigateReasoning}
              className="mt-4 inline-flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)]"
            >
              Use In Reasoning View
              <Orbit size={14} />
            </button>
          </div>

          <div className="space-y-3">
            {isLoadingTemplates ? (
              <div className="text-[14px] leading-7 text-[var(--mw-muted)]">Loading templates...</div>
            ) : templates.length ? (
              templates.map((template) => (
                <div
                  key={template.template_id}
                  className={`rounded-[20px] border px-4 py-4 ${
                    template.template_id === task.template_id
                      ? "border-[var(--mw-accent)] bg-[var(--mw-accent-soft)]"
                      : "border-[var(--mw-border)] bg-[var(--mw-node)]"
                  }`}
                >
                  <div className="font-serif text-[20px] text-[var(--mw-text)]">{template.name}</div>
                  <div className="mt-2 text-[13px] leading-6 text-[var(--mw-muted)]">{template.description}</div>
                  <div className="mt-3 font-mono text-[11px] text-[var(--mw-subtle)]">{template.template_id}</div>
                </div>
              ))
            ) : (
              <div className="text-[14px] leading-7 text-[var(--mw-muted)]">No templates are available from the backend.</div>
            )}
          </div>
        </div>
      </Panel>
    </div>
  );
}

function SettingsView({
  task,
  determinismMode,
  controlLevel,
  autoApproveHumanReview,
  onDeterminismModeChange,
  onControlLevelChange,
  onAutoApproveHumanReviewChange,
}: Pick<
  OperationsViewProps,
  | "task"
  | "determinismMode"
  | "controlLevel"
  | "autoApproveHumanReview"
  | "onDeterminismModeChange"
  | "onControlLevelChange"
  | "onAutoApproveHumanReviewChange"
>) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4 pt-4">
      <Panel title="Runtime Defaults" eyebrow="Control Surface" icon={Settings2}>
        <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
          <div className="space-y-4">
            <label className="block rounded-[20px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
              <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Determinism Mode</div>
              <select
                value={determinismMode}
                onChange={(event) => onDeterminismModeChange(event.target.value as DeterminismMode)}
                className="mt-3 w-full rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
              >
                <option value="non_deterministic">Non-deterministic</option>
                <option value="best_effort_deterministic">Best-effort deterministic</option>
                <option value="strict_deterministic">Strict deterministic</option>
              </select>
            </label>

            <label className="block rounded-[20px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
              <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Control Level</div>
              <select
                value={controlLevel}
                onChange={(event) => onControlLevelChange(event.target.value as ControlLevel)}
                className="mt-3 w-full rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
              >
                <option value="exploratory">Exploratory</option>
                <option value="operational">Operational</option>
                <option value="regulated">Regulated</option>
                <option value="strict_audit">Strict audit</option>
              </select>
            </label>

            <label className="flex items-center gap-3 rounded-[20px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4 text-[14px] text-[var(--mw-text)]">
              <input
                type="checkbox"
                checked={autoApproveHumanReview}
                onChange={(event) => onAutoApproveHumanReviewChange(event.target.checked)}
                className="h-4 w-4 accent-[var(--mw-accent)]"
              />
              Auto-approve human review gates
            </label>
          </div>

          <div className="space-y-4">
            <div className="rounded-[20px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
              <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Active Setting Impact</div>
              <div className="mt-3 text-[14px] leading-7 text-[var(--mw-muted)]">
                Determinism mode and control level are sent with every execution request. They drive model routing, logging depth, trace visibility, and whether human approval is expected for higher-stakes conclusions.
              </div>
            </div>
            <div className="rounded-[20px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
              <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Current Runtime Snapshot</div>
              <div className="mt-3 space-y-2 text-[13px] leading-6 text-[var(--mw-muted)]">
                <div>Task Mode: {humanize(task.determinism_mode ?? "unknown")}</div>
                <div>Task Control Level: {humanize(task.control_level ?? "unknown")}</div>
                <div>Task Model Version: {task.model_version || task.model_id || "Unavailable"}</div>
                <div>Execution Env Hash: <span className="font-mono text-[var(--mw-text)]">{shortHash(task.execution_env_hash)}</span></div>
              </div>
            </div>
          </div>
        </div>
      </Panel>
    </div>
  );
}

export function OperationsView(props: OperationsViewProps) {
  if (props.activeItem === "dashboard") {
    return (
      <DashboardView
        task={props.task}
        history={props.history}
        offlineDemo={props.offlineDemo}
        notice={props.notice}
        onSelectTask={props.onSelectTask}
        onNavigateReasoning={props.onNavigateReasoning}
      />
    );
  }

  if (props.activeItem === "history") {
    return (
      <HistoryView
        task={props.task}
        history={props.history}
        isLoadingTask={props.isLoadingTask}
        isReplayingTask={props.isReplayingTask}
        notice={props.notice}
        onSelectTask={props.onSelectTask}
        onReplayTask={props.onReplayTask}
      />
    );
  }

  if (props.activeItem === "audit-log") {
    return <AuditView task={props.task} notice={props.notice} />;
  }

  if (props.activeItem === "templates") {
    return (
      <TemplatesView
        task={props.task}
        templates={props.templates}
        isLoadingTemplates={props.isLoadingTemplates}
        onNavigateReasoning={props.onNavigateReasoning}
      />
    );
  }

  if (props.activeItem === "settings") {
    return (
      <SettingsView
        task={props.task}
        determinismMode={props.determinismMode}
        controlLevel={props.controlLevel}
        autoApproveHumanReview={props.autoApproveHumanReview}
        onDeterminismModeChange={props.onDeterminismModeChange}
        onControlLevelChange={props.onControlLevelChange}
        onAutoApproveHumanReviewChange={props.onAutoApproveHumanReviewChange}
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4 pt-4">
      <EmptyState
        title="Use The Reasoning Workspace"
        body="The interactive execution graph, node inspector, planner, replay, diff, and trace tooling are available from the reasoning workspace."
        actionLabel="Open Reasoning"
        onAction={props.onNavigateReasoning}
      />
    </div>
  );
}
