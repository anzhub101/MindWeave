import { useEffect, useMemo, useState, type ComponentProps, type ReactNode } from "react";
import { X } from "lucide-react";
import {
  applyPlannedChange,
  changeNodeExecutor,
  diffTaskRuns,
  fetchAuditPackage,
  fetchNodeDetail,
  fetchReasoningTrace,
  fetchTask,
  fetchTasks,
  fetchTemplates,
  executeTask,
  planNodeChange,
  planTaskChange,
  replayTask,
  submitReview,
} from "./api";
import { ChangePlannerPanel } from "./components/ChangePlannerPanel";
import { GraphCanvas } from "./components/GraphCanvas";
import { HeaderBar } from "./components/HeaderBar";
import { InspectorDrawer } from "./components/InspectorDrawer";
import { OperationsView } from "./components/OperationsView";
import { PromptComposer } from "./components/PromptComposer";
import { RunWorkbenchPanel } from "./components/RunWorkbenchPanel";
import { Sidebar } from "./components/Sidebar";
import { SummaryCard } from "./components/SummaryCard";
import { mockHistory, mockTask, mockTemplates } from "./mockData";
import type {
  ControlLevel,
  DeterminismMode,
  GraphNode,
  NodeDetailResponse,
  PlanChangeResponse,
  ReasoningTraceResponse,
  ReasoningVisibilityTier,
  RunDiffResponse,
  TaskRunListItem,
  TaskRunResponse,
  TemplateSummary,
  TraceAccessRole,
} from "./types";

function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function formatError(error: unknown) {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "The requested operation could not be completed.";
}

export default function App() {
  const [activeItem, setActiveItem] = useState("reasoning");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [activeReasoningModal, setActiveReasoningModal] = useState<"compose" | "workbench" | null>(null);
  const [rightPanelWidth, setRightPanelWidth] = useState(368);
  const [prompt, setPrompt] = useState(mockTask.prompt);
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);
  const [task, setTask] = useState<TaskRunResponse>(mockTask);
  const [history, setHistory] = useState<TaskRunListItem[]>(mockHistory);
  const [templates, setTemplates] = useState<TemplateSummary[]>(mockTemplates);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeDetail, setSelectedNodeDetail] = useState<NodeDetailResponse | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPlanningChange, setIsPlanningChange] = useState(false);
  const [isApplyingPlannedChange, setIsApplyingPlannedChange] = useState(false);
  const [isLoadingTask, setIsLoadingTask] = useState(false);
  const [isLoadingNodeDetail, setIsLoadingNodeDetail] = useState(false);
  const [isReplayingTask, setIsReplayingTask] = useState(false);
  const [isLoadingTrace, setIsLoadingTrace] = useState(false);
  const [isDiffingRuns, setIsDiffingRuns] = useState(false);
  const [isLoadingTemplates, setIsLoadingTemplates] = useState(false);
  const [offlineDemo, setOfflineDemo] = useState(true);
  const [determinismMode, setDeterminismMode] = useState<DeterminismMode>("best_effort_deterministic");
  const [controlLevel, setControlLevel] = useState<ControlLevel>("operational");
  const [autoApproveHumanReview, setAutoApproveHumanReview] = useState(true);
  const [plannedChange, setPlannedChange] = useState<PlanChangeResponse | null>(null);
  const [reasoningTrace, setReasoningTrace] = useState<ReasoningTraceResponse | null>(null);
  const [traceTier, setTraceTier] = useState<ReasoningVisibilityTier>("structured_reasoning_trace");
  const [traceViewerRole, setTraceViewerRole] = useState<TraceAccessRole>("reviewer");
  const [traceViewerId, setTraceViewerId] = useState("dashboard-user");
  const [compareTaskId, setCompareTaskId] = useState("");
  const [runDiff, setRunDiff] = useState<RunDiffResponse | null>(null);
  const [workspaceNotice, setWorkspaceNotice] = useState<{ tone: "info" | "error"; message: string } | null>(null);
  const [animatedStatuses, setAnimatedStatuses] = useState<Record<string, GraphNode["status"]>>(
    () =>
      Object.fromEntries(
        mockTask.nodes.map((node, index) => [node.id, index === 0 ? "completed" : "pending"]),
      ) as Record<string, GraphNode["status"]>,
  );

  function syncTaskState(nextTask: TaskRunResponse) {
    setTask(nextTask);
    setPrompt(nextTask.prompt);
    setDeterminismMode(nextTask.determinism_mode ?? "best_effort_deterministic");
    setControlLevel(nextTask.control_level ?? "operational");
    setTraceTier(nextTask.default_visibility_tier ?? "structured_reasoning_trace");
  }

  useEffect(() => {
    let cancelled = false;

    async function loadInitialData() {
      try {
        setIsLoadingTemplates(true);
        const [tasks, availableTemplates] = await Promise.all([
          fetchTasks(),
          fetchTemplates().catch(() => mockTemplates),
        ]);
        if (cancelled) {
          return;
        }
        setHistory(tasks);
        setTemplates(availableTemplates);
        setOfflineDemo(false);
        if (tasks.length > 0) {
          const latestTask = await fetchTask(tasks[0].task_id);
          if (cancelled) {
            return;
          }
          syncTaskState(latestTask);
        }
      } catch {
        if (cancelled) {
          return;
        }
        setHistory(mockHistory);
        setTemplates(mockTemplates);
        setTask(mockTask);
        setOfflineDemo(true);
      } finally {
        if (!cancelled) {
          setIsLoadingTemplates(false);
        }
      }
    }

    void loadInitialData();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const nextStatuses = Object.fromEntries(
      task.nodes.map((node) => [node.id, "pending"]),
    ) as Record<string, GraphNode["status"]>;
    setAnimatedStatuses(nextStatuses);

    const timeouts = task.nodes.map((node, index) =>
      window.setTimeout(() => {
        setAnimatedStatuses((current) => ({
          ...current,
          [node.id]: node.status,
        }));
      }, 180 + index * 220),
    );

    return () => {
      timeouts.forEach((timeout) => window.clearTimeout(timeout));
    };
  }, [task]);

  useEffect(() => {
    if (!summaryOpen && activeReasoningModal === null) {
      return;
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSummaryOpen(false);
        setActiveReasoningModal(null);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activeReasoningModal, summaryOpen]);

  useEffect(() => {
    setPlannedChange(null);
    setRunDiff(null);
    setCompareTaskId((current) => (current === task.task_id ? "" : current));
  }, [task.task_id, selectedNodeId]);

  useEffect(() => {
    if (offlineDemo || task.task_id === "demo-task") {
      setReasoningTrace(null);
      return;
    }

    let cancelled = false;
    setIsLoadingTrace(true);
    fetchReasoningTrace(task.task_id, traceTier, traceViewerRole, traceViewerId)
      .then((response) => {
        if (!cancelled) {
          setReasoningTrace(response);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setReasoningTrace(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoadingTrace(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [offlineDemo, task.task_id, traceTier, traceViewerRole, traceViewerId]);

  useEffect(() => {
    if (offlineDemo || task.task_id === "demo-task" || !selectedNodeId) {
      setSelectedNodeDetail(null);
      return;
    }

    let cancelled = false;
    setIsLoadingNodeDetail(true);
    fetchNodeDetail(task.task_id, selectedNodeId)
      .then((detail) => {
        if (!cancelled) {
          setSelectedNodeDetail(detail);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSelectedNodeDetail(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoadingNodeDetail(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [offlineDemo, selectedNodeId, task.task_id]);

  const displayNodes = useMemo(
    () =>
      task.nodes.map((node) => ({
        ...node,
        status: animatedStatuses[node.id] ?? node.status,
      })),
    [animatedStatuses, task.nodes],
  );

  const selectedNode = displayNodes.find((node) => node.id === selectedNodeId) ?? null;
  const isReasoningView = activeItem === "reasoning";
  const pageTitle =
    activeItem === "reasoning"
      ? "Reasoning"
      : activeItem === "dashboard"
        ? "Main Dashboard"
        : activeItem.replace(/-/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
  const pageEyebrow =
    activeItem === "reasoning" ? "Trace Workspace" : activeItem === "dashboard" ? "MindWeave Operator" : "Workspace";

  function handleToggleSummary() {
    setActiveReasoningModal(null);
    setSummaryOpen((current) => !current);
  }

  function openReasoningModal(modal: "compose" | "workbench") {
    setSummaryOpen(false);
    setActiveReasoningModal(modal);
  }

  async function refreshTaskGraph(taskId: string, preserveNodeId: string | null = selectedNodeId) {
    const nextTask = await fetchTask(taskId);
    syncTaskState(nextTask);
    if (preserveNodeId && nextTask.nodes.some((node) => node.id === preserveNodeId)) {
      setSelectedNodeId(preserveNodeId);
    } else {
      setSelectedNodeId(null);
      setSelectedNodeDetail(null);
    }
    return nextTask;
  }

  async function handleSubmit() {
    setIsSubmitting(true);
    try {
      const nextTask = await executeTask(prompt, uploadedFiles, determinismMode, controlLevel, autoApproveHumanReview);
      syncTaskState(nextTask);
      setSelectedNodeId(null);
      setSelectedNodeDetail(null);
      setOfflineDemo(false);
      setWorkspaceNotice({
        tone: "info",
        message: `Executed ${nextTask.task_id} in ${nextTask.determinism_mode?.replace(/_/g, " ") ?? "runtime"} mode.`,
      });
      const latestHistory = await fetchTasks().catch(() => history);
      setHistory(latestHistory);
    } catch (error) {
      setTask(mockTask);
      setSelectedNodeId(null);
      setOfflineDemo(true);
      setWorkspaceNotice({
        tone: "error",
        message: formatError(error),
      });
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleReview(decision: "approved" | "rejected") {
    if (!task.pending_review_node_id || offlineDemo) {
      return;
    }
    setIsSubmitting(true);
    try {
      const nextTask = await submitReview(task.task_id, task.pending_review_node_id, decision);
      await refreshTaskGraph(nextTask.task_id, selectedNodeId);
      const latestHistory = await fetchTasks().catch(() => history);
      setHistory(latestHistory);
      setWorkspaceNotice({
        tone: "info",
        message: `Review ${decision} recorded for ${task.pending_review_node_id}.`,
      });
    } catch (error) {
      setWorkspaceNotice({
        tone: "error",
        message: formatError(error),
      });
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleExport() {
    if (offlineDemo || task.task_id === "demo-task") {
      downloadJson("mindweave-audit-demo.json", task);
      return;
    }
    try {
      const auditPackage = await fetchAuditPackage(task.task_id);
      downloadJson(`mindweave-audit-${task.task_id}.json`, auditPackage);
    } catch {
      downloadJson(`mindweave-audit-${task.task_id}.json`, task);
    }
  }

  async function handlePlanChange(requestText: string) {
    if (offlineDemo) {
      return;
    }
    setIsPlanningChange(true);
    try {
      const nextPlan = await planTaskChange(task.task_id, requestText, "dashboard-user", null);
      setPlannedChange(nextPlan);
      setWorkspaceNotice({
        tone: nextPlan.status === "needs_clarification" ? "error" : "info",
        message:
          nextPlan.status === "needs_clarification"
            ? nextPlan.clarification_question ?? "The planner needs more detail before it can generate a patch."
            : "Patch proposal generated from the natural-language request.",
      });
    } catch (error) {
      setPlannedChange(null);
      setWorkspaceNotice({
        tone: "error",
        message: formatError(error),
      });
    } finally {
      setIsPlanningChange(false);
    }
  }

  async function handleApplyPlannedChange(proposalId: string, approvedBy: string, autoRerun: boolean) {
    if (offlineDemo) {
      return;
    }
    setIsApplyingPlannedChange(true);
    try {
      const nextTask = await applyPlannedChange(task.task_id, proposalId, approvedBy, autoRerun);
      await refreshTaskGraph(nextTask.task_id, selectedNodeId);
      setPlannedChange(null);
      const latestHistory = await fetchTasks().catch(() => history);
      setHistory(latestHistory);
      setWorkspaceNotice({
        tone: "info",
        message: `Applied planned change to ${nextTask.task_id}${autoRerun ? " and reran the affected scope" : ""}.`,
      });
    } catch (error) {
      setPlannedChange((current) => current);
      setWorkspaceNotice({
        tone: "error",
        message: formatError(error),
      });
    } finally {
      setIsApplyingPlannedChange(false);
    }
  }

  async function handleSelectTask(taskId: string) {
    if (offlineDemo || taskId === task.task_id) {
      return;
    }
    setIsLoadingTask(true);
    try {
      await refreshTaskGraph(taskId, null);
      setSelectedNodeId(null);
      setSelectedNodeDetail(null);
      setWorkspaceNotice({
        tone: "info",
        message: `Loaded run ${taskId}.`,
      });
    } catch (error) {
      setWorkspaceNotice({
        tone: "error",
        message: formatError(error),
      });
    } finally {
      setIsLoadingTask(false);
    }
  }

  async function handleReplayTask() {
    if (offlineDemo || task.task_id === "demo-task") {
      return;
    }
    setIsReplayingTask(true);
    try {
      const nextTask = await replayTask(task.task_id, autoApproveHumanReview);
      await refreshTaskGraph(nextTask.task_id, selectedNodeId);
      const latestHistory = await fetchTasks().catch(() => history);
      setHistory(latestHistory);
      setWorkspaceNotice({
        tone: "info",
        message: `Replayed run ${task.task_id}.`,
      });
    } catch (error) {
      setWorkspaceNotice({
        tone: "error",
        message: formatError(error),
      });
    } finally {
      setIsReplayingTask(false);
    }
  }

  async function handleRunDiff() {
    if (offlineDemo || !compareTaskId) {
      return;
    }
    setIsDiffingRuns(true);
    try {
      const diff = await diffTaskRuns(task.task_id, compareTaskId);
      setRunDiff(diff);
      setWorkspaceNotice({
        tone: "info",
        message: `Compared ${task.task_id} against ${compareTaskId}.`,
      });
    } catch (error) {
      setWorkspaceNotice({
        tone: "error",
        message: formatError(error),
      });
    } finally {
      setIsDiffingRuns(false);
    }
  }

  async function handlePlanNodeChange(nodeId: string, requestText: string) {
    if (offlineDemo) {
      return;
    }
    setIsPlanningChange(true);
    try {
      const nextPlan = await planNodeChange(task.task_id, nodeId, requestText, "dashboard-user");
      setPlannedChange(nextPlan);
      setWorkspaceNotice({
        tone: nextPlan.status === "needs_clarification" ? "error" : "info",
        message:
          nextPlan.status === "needs_clarification"
            ? nextPlan.clarification_question ?? "The node change needs more detail before it can be proposed."
            : `Prepared a node-scoped change proposal for ${nodeId}.`,
      });
    } catch (error) {
      setWorkspaceNotice({
        tone: "error",
        message: formatError(error),
      });
    } finally {
      setIsPlanningChange(false);
    }
  }

  async function handleChangeNodeExecutor(
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
  ) {
    if (offlineDemo) {
      return;
    }
    setIsSubmitting(true);
    try {
      const nextTask = await changeNodeExecutor(task.task_id, nodeId, payload);
      await refreshTaskGraph(nextTask.task_id, nodeId);
      const latestHistory = await fetchTasks().catch(() => history);
      setHistory(latestHistory);
      setWorkspaceNotice({
        tone: "info",
        message: `Updated execution mode for ${nodeId}.`,
      });
    } catch (error) {
      setWorkspaceNotice({
        tone: "error",
        message: formatError(error),
      });
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div data-theme={theme} className="h-screen overflow-hidden bg-[var(--mw-page)] text-[var(--mw-text)]">
      <div className="flex h-full">
        <Sidebar
          activeItem={activeItem}
          onSelect={setActiveItem}
          theme={theme}
          onToggleTheme={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
        />

        <main className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-[var(--mw-page)]">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(255,255,255,0.05),_transparent_38%),radial-gradient(circle_at_bottom,_rgba(184,154,106,0.06),_transparent_30%)]" />
          <HeaderBar
            pageTitle={pageTitle}
            pageEyebrow={pageEyebrow}
            summaryOpen={summaryOpen}
            onToggleSummary={handleToggleSummary}
            contextActions={
              isReasoningView ? (
                <>
                  <button
                    type="button"
                    onClick={() => openReasoningModal("compose")}
                    className={`flex h-11 items-center rounded-[18px] border px-4 text-sm transition ${
                      activeReasoningModal === "compose"
                        ? "border-[var(--mw-accent)] bg-[var(--mw-accent-soft)] text-[var(--mw-text)]"
                        : "border-[var(--mw-border)] bg-[var(--mw-panel)] text-[var(--mw-text)] hover:border-[var(--mw-accent)]"
                    }`}
                  >
                    Compose A Run
                  </button>
                  <button
                    type="button"
                    onClick={() => openReasoningModal("workbench")}
                    className={`flex h-11 items-center rounded-[18px] border px-4 text-sm transition ${
                      activeReasoningModal === "workbench"
                        ? "border-[var(--mw-accent)] bg-[var(--mw-accent-soft)] text-[var(--mw-text)]"
                        : "border-[var(--mw-border)] bg-[var(--mw-panel)] text-[var(--mw-text)] hover:border-[var(--mw-accent)]"
                    }`}
                  >
                    Run Workbench
                  </button>
                </>
              ) : null
            }
          />

          {isReasoningView ? (
            <>
              <ReasoningWorkspace
                rightPanelWidth={rightPanelWidth}
                onRightPanelWidthChange={setRightPanelWidth}
                summaryOpen={summaryOpen}
                onCloseSummary={() => setSummaryOpen(false)}
                summaryProps={{
                  status: task.status,
                  determinismMode: task.determinism_mode,
                  controlLevel: task.control_level,
                  modelVersion: task.model_version,
                  summary: task.final_summary,
                  pendingReviewNodeId: task.pending_review_node_id,
                  onApproveReview: () => void handleReview("approved"),
                  onRejectReview: () => void handleReview("rejected"),
                  onDismiss: () => setSummaryOpen(false),
                  onExport: handleExport,
                }}
                sidePanel={
                  <>
                    <ChangePlannerPanel
                      offlineDemo={offlineDemo}
                      selectedNodeId={null}
                      selectedNodeTitle={null}
                      planResult={plannedChange}
                      isPlanning={isPlanningChange}
                      isApplying={isApplyingPlannedChange}
                      onPlanChange={handlePlanChange}
                      onApplyPlannedChange={handleApplyPlannedChange}
                    />
                    {selectedNode ? (
                      <InspectorDrawer
                        node={selectedNode}
                        nodeDetail={selectedNodeDetail}
                        planResult={plannedChange}
                        isLoading={isLoadingNodeDetail}
                        isPlanning={isPlanningChange}
                        isApplying={isApplyingPlannedChange}
                        isUpdatingExecutor={isSubmitting}
                        onPlanNodeChange={handlePlanNodeChange}
                        onApplyPlannedChange={handleApplyPlannedChange}
                        onChangeExecutor={handleChangeNodeExecutor}
                        onClose={() => {
                          setSelectedNodeId(null);
                          setSelectedNodeDetail(null);
                        }}
                      />
                    ) : null}
                  </>
                }
              >
                <div className="flex min-h-0 min-w-0 flex-col gap-4">
                  <GraphCanvas
                    programId={task.program_id}
                    nodes={displayNodes}
                    edges={task.edges}
                    selectedNodeId={selectedNodeId}
                    onSelectNode={(node) => {
                      setSelectedNodeId(node.id);
                      setSelectedNodeDetail(null);
                    }}
                  />
                </div>
              </ReasoningWorkspace>

              <OverlayModal
                open={activeReasoningModal === "compose"}
                title="Compose A Run"
                onClose={() => setActiveReasoningModal(null)}
              >
                <PromptComposer
                  prompt={prompt}
                  onPromptChange={setPrompt}
                  onSubmit={handleSubmit}
                  onFileSelect={setUploadedFiles}
                  determinismMode={determinismMode}
                  onDeterminismModeChange={setDeterminismMode}
                  controlLevel={controlLevel}
                  onControlLevelChange={setControlLevel}
                  autoApproveHumanReview={autoApproveHumanReview}
                  onAutoApproveHumanReviewChange={setAutoApproveHumanReview}
                  files={uploadedFiles}
                  isSubmitting={isSubmitting}
                  offlineDemo={offlineDemo}
                  isNodeSelected={false}
                />
              </OverlayModal>

              <OverlayModal
                open={activeReasoningModal === "workbench"}
                title="Run Workbench"
                onClose={() => setActiveReasoningModal(null)}
              >
                <RunWorkbenchPanel
                  task={task}
                  history={history}
                  offlineDemo={offlineDemo}
                  compareTaskId={compareTaskId}
                  traceTier={traceTier}
                  traceViewerRole={traceViewerRole}
                  traceViewerId={traceViewerId}
                  trace={reasoningTrace}
                  diff={runDiff}
                  isLoadingTask={isLoadingTask}
                  isReplaying={isReplayingTask}
                  isTracing={isLoadingTrace}
                  isDiffing={isDiffingRuns}
                  notice={workspaceNotice}
                  onSelectTask={handleSelectTask}
                  onReplayTask={handleReplayTask}
                  onCompareTaskChange={setCompareTaskId}
                  onRunDiff={handleRunDiff}
                  onTraceTierChange={setTraceTier}
                  onTraceViewerRoleChange={setTraceViewerRole}
                  onTraceViewerIdChange={setTraceViewerId}
                />
              </OverlayModal>
            </>
          ) : (
            <div className="relative flex min-h-0 flex-1 bg-transparent">
              {summaryOpen ? (
                <div className="absolute inset-0 z-30 flex items-center justify-center p-6 lg:p-10">
                  <div
                    className="absolute inset-0 bg-[color:rgba(0,0,0,0.28)] backdrop-blur-md"
                    onClick={() => setSummaryOpen(false)}
                    aria-hidden="true"
                  />
                  <div
                    role="dialog"
                    aria-modal="true"
                    aria-label="Run summary"
                    className="relative z-10 h-[80vh] w-[min(80vw,960px)]"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <SummaryCard
                      status={task.status}
                      determinismMode={task.determinism_mode}
                      controlLevel={task.control_level}
                      modelVersion={task.model_version}
                      summary={task.final_summary}
                      pendingReviewNodeId={task.pending_review_node_id}
                      onApproveReview={() => void handleReview("approved")}
                      onRejectReview={() => void handleReview("rejected")}
                      onDismiss={() => setSummaryOpen(false)}
                      onExport={handleExport}
                    />
                  </div>
                </div>
              ) : null}
              <OperationsView
                activeItem={activeItem}
                task={task}
                history={history}
                templates={templates}
                offlineDemo={offlineDemo}
                isLoadingTask={isLoadingTask}
                isLoadingTemplates={isLoadingTemplates}
                isReplayingTask={isReplayingTask}
                notice={workspaceNotice}
                determinismMode={determinismMode}
                controlLevel={controlLevel}
                autoApproveHumanReview={autoApproveHumanReview}
                onDeterminismModeChange={setDeterminismMode}
                onControlLevelChange={setControlLevel}
                onAutoApproveHumanReviewChange={setAutoApproveHumanReview}
                onSelectTask={handleSelectTask}
                onReplayTask={handleReplayTask}
                onNavigateReasoning={() => setActiveItem("reasoning")}
              />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

interface ReasoningWorkspaceProps {
  children: ReactNode;
  rightPanelWidth: number;
  onRightPanelWidthChange: (value: number) => void;
  sidePanel: ReactNode;
  summaryOpen: boolean;
  onCloseSummary: () => void;
  summaryProps: ComponentProps<typeof SummaryCard>;
}

function ReasoningWorkspace({
  children,
  rightPanelWidth,
  onRightPanelWidthChange,
  sidePanel,
  summaryOpen,
  onCloseSummary,
  summaryProps,
}: ReasoningWorkspaceProps) {
  return (
    <div className="relative flex min-h-0 flex-1">
      {summaryOpen ? (
        <div className="absolute inset-0 z-30 flex items-center justify-center p-6 lg:p-10">
          <div
            className="absolute inset-0 bg-[color:rgba(0,0,0,0.28)] backdrop-blur-md"
            onClick={onCloseSummary}
            aria-hidden="true"
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Run summary"
            className="relative z-10 h-[80vh] w-[min(80vw,960px)]"
            onClick={(event) => event.stopPropagation()}
          >
            <SummaryCard {...summaryProps} />
          </div>
        </div>
      ) : null}

      <div className="min-h-0 min-w-0 flex-1 px-4 pb-4 pt-4">{children}</div>
      <PanelResizeHandle width={rightPanelWidth} onWidthChange={onRightPanelWidthChange} />
      <aside
        className="min-h-0 border-l border-[var(--mw-border)] bg-[var(--mw-page)] px-3 pb-3 pt-3"
        style={{ width: rightPanelWidth }}
      >
        <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto pr-1">
          {sidePanel}
        </div>
      </aside>
    </div>
  );
}

interface OverlayModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}

function OverlayModal({ open, title, onClose, children }: OverlayModalProps) {
  if (!open) {
    return null;
  }

  return (
    <div className="absolute inset-0 z-40 flex items-center justify-center p-4 lg:p-8">
      <div
        className="absolute inset-0 bg-[color:rgba(0,0,0,0.36)] backdrop-blur-md"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative z-10 flex h-[80vh] w-[min(80vw,1400px)] flex-col overflow-hidden rounded-[28px] border border-[var(--mw-border)] bg-[var(--mw-page)] shadow-[0_40px_120px_rgba(0,0,0,0.35)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--mw-border)] px-5 py-4">
          <div>
            <div className="text-[10px] uppercase tracking-[0.24em] text-[var(--mw-subtle)]">Reasoning Workspace</div>
            <div className="mt-1 font-serif text-[28px] leading-none text-[var(--mw-text)]">{title}</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-10 w-10 items-center justify-center rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)]"
          >
            <X size={16} strokeWidth={1.8} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 lg:px-5">
          {children}
        </div>
      </div>
    </div>
  );
}
interface PanelResizeHandleProps {
  width: number;
  onWidthChange: (value: number) => void;
}

export function PanelResizeHandle({ width, onWidthChange }: PanelResizeHandleProps) {
  const [isDragging, setIsDragging] = useState(false);

  function handlePointerDown(event: React.PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    setIsDragging(true);

    const startX = event.clientX;
    const startWidth = width;
    document.body.style.userSelect = "none";

    function handlePointerMove(moveEvent: PointerEvent) {
      const delta = startX - moveEvent.clientX;
      onWidthChange(Math.min(520, Math.max(300, startWidth + delta)));
    }

    function handlePointerUp(upEvent: PointerEvent) {
      handle.releasePointerCapture(upEvent.pointerId);
      setIsDragging(false);
      document.body.style.userSelect = "";
      handle.removeEventListener("pointermove", handlePointerMove);
      handle.removeEventListener("pointerup", handlePointerUp);
    }

    handle.addEventListener("pointermove", handlePointerMove);
    handle.addEventListener("pointerup", handlePointerUp);
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize reasoning side panel"
      onPointerDown={handlePointerDown}
      className={`relative z-20 flex w-4 cursor-col-resize items-center justify-center transition-colors hover:bg-[var(--mw-node)] ${
        isDragging ? "bg-[var(--mw-node)]" : "bg-transparent"
      }`}
    >
      <div
        className={`absolute inset-y-0 w-px transition-colors ${
          isDragging ? "bg-[var(--mw-accent)]" : "bg-[var(--mw-border)]"
        }`}
      />
      <div className="z-10 flex h-6 flex-col justify-between">
        <div className={`h-[3px] w-[3px] rounded-full transition-colors ${isDragging ? "bg-[var(--mw-accent)]" : "bg-[var(--mw-border-strong)]"}`} />
        <div className={`h-[3px] w-[3px] rounded-full transition-colors ${isDragging ? "bg-[var(--mw-accent)]" : "bg-[var(--mw-border-strong)]"}`} />
        <div className={`h-[3px] w-[3px] rounded-full transition-colors ${isDragging ? "bg-[var(--mw-accent)]" : "bg-[var(--mw-border-strong)]"}`} />
      </div>
    </div>
  );
}
