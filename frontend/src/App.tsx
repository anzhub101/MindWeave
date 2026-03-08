import { useEffect, useMemo, useState, type ComponentProps, type ReactNode } from "react";
import { applyPlannedChange, fetchAuditPackage, fetchTasks, executeTask, planTaskChange, submitReview } from "./api";
import { ChangePlannerPanel } from "./components/ChangePlannerPanel";
import { GraphCanvas } from "./components/GraphCanvas";
import { HeaderBar } from "./components/HeaderBar";
import { InspectorDrawer } from "./components/InspectorDrawer";
import { PromptComposer } from "./components/PromptComposer";
import { Sidebar } from "./components/Sidebar";
import { SummaryCard } from "./components/SummaryCard";
import { mockHistory, mockTask } from "./mockData";
import type { GraphNode, PlanChangeResponse, TaskRunListItem, TaskRunResponse } from "./types";

function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function App() {
  const [activeItem, setActiveItem] = useState("reasoning");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [rightPanelWidth, setRightPanelWidth] = useState(368);
  const [prompt, setPrompt] = useState(mockTask.prompt);
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);
  const [task, setTask] = useState<TaskRunResponse>(mockTask);
  const [history, setHistory] = useState<TaskRunListItem[]>(mockHistory);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPlanningChange, setIsPlanningChange] = useState(false);
  const [isApplyingPlannedChange, setIsApplyingPlannedChange] = useState(false);
  const [offlineDemo, setOfflineDemo] = useState(true);
  const [deterministic, setDeterministic] = useState(true);
  const [autoApproveHumanReview, setAutoApproveHumanReview] = useState(true);
  const [plannedChange, setPlannedChange] = useState<PlanChangeResponse | null>(null);
  const [animatedStatuses, setAnimatedStatuses] = useState<Record<string, GraphNode["status"]>>(
    () =>
      Object.fromEntries(
        mockTask.nodes.map((node, index) => [node.id, index === 0 ? "completed" : "pending"]),
      ) as Record<string, GraphNode["status"]>,
  );

  useEffect(() => {
    fetchTasks()
      .then((tasks) => {
        setHistory(tasks);
        if (tasks.length > 0 && !offlineDemo) {
          setSelectedNodeId((current) => current);
        }
      })
      .catch(() => {
        setHistory(mockHistory);
      });
  }, [offlineDemo]);

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
    if (!summaryOpen) {
      return;
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSummaryOpen(false);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [summaryOpen]);

  useEffect(() => {
    setPlannedChange(null);
  }, [task.task_id, selectedNodeId]);

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

  async function handleSubmit() {
    setIsSubmitting(true);
    try {
      const nextTask = await executeTask(prompt, uploadedFiles, deterministic, autoApproveHumanReview);
      setTask(nextTask);
      setSelectedNodeId(null);
      setOfflineDemo(false);
      const latestHistory = await fetchTasks().catch(() => history);
      setHistory(latestHistory);
    } catch {
      setTask(mockTask);
      setSelectedNodeId(null);
      setOfflineDemo(true);
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
      setTask(nextTask);
      setSelectedNodeId(null);
      const latestHistory = await fetchTasks().catch(() => history);
      setHistory(latestHistory);
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
      const nextPlan = await planTaskChange(task.task_id, requestText, "dashboard-user", selectedNodeId);
      setPlannedChange(nextPlan);
    } catch {
      setPlannedChange(null);
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
      setTask(nextTask);
      setPlannedChange(null);
      const latestHistory = await fetchTasks().catch(() => history);
      setHistory(latestHistory);
    } catch {
      setPlannedChange((current) => current);
    } finally {
      setIsApplyingPlannedChange(false);
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
            onToggleSummary={() => setSummaryOpen((current) => !current)}
          />

          {isReasoningView ? (
            <ReasoningWorkspace
              rightPanelWidth={rightPanelWidth}
              onRightPanelWidthChange={setRightPanelWidth}
              summaryOpen={summaryOpen}
              onCloseSummary={() => setSummaryOpen(false)}
              summaryProps={{
                status: task.status,
                summary: task.final_summary,
                pendingReviewNodeId: task.pending_review_node_id,
                onApproveReview: () => void handleReview("approved"),
                onRejectReview: () => void handleReview("rejected"),
                onDismiss: () => setSummaryOpen(false),
                onExport: handleExport,
              }}
              promptComposer={
                <>
                  <PromptComposer
                    prompt={prompt}
                    onPromptChange={setPrompt}
                    onSubmit={handleSubmit}
                    onFileSelect={setUploadedFiles}
                    deterministic={deterministic}
                    onDeterministicChange={setDeterministic}
                    autoApproveHumanReview={autoApproveHumanReview}
                    onAutoApproveHumanReviewChange={setAutoApproveHumanReview}
                    files={uploadedFiles}
                    isSubmitting={isSubmitting}
                    offlineDemo={offlineDemo}
                    isNodeSelected={!!selectedNode}
                  />
                  <ChangePlannerPanel
                    offlineDemo={offlineDemo}
                    selectedNodeId={selectedNodeId}
                    selectedNodeTitle={selectedNode?.title ?? null}
                    planResult={plannedChange}
                    isPlanning={isPlanningChange}
                    isApplying={isApplyingPlannedChange}
                    onPlanChange={handlePlanChange}
                    onApplyPlannedChange={handleApplyPlannedChange}
                  />
                </>
              }
              inspector={
                selectedNode ? (
                  <InspectorDrawer
                    node={selectedNode}
                    documents={task.source_documents}
                    onClose={() => setSelectedNodeId(null)}
                  />
                ) : null
              }
            >
              <div className="flex min-h-0 min-w-0 flex-col gap-4">
                <GraphCanvas
                  programId={task.program_id}
                  nodes={displayNodes}
                  edges={task.edges}
                  selectedNodeId={selectedNodeId}
                  onSelectNode={(node) => setSelectedNodeId(node.id)}
                />
              </div>
            </ReasoningWorkspace>
          ) : (
            <div className="relative flex min-h-0 flex-1 bg-transparent" />
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
  promptComposer: ReactNode;
  inspector: ReactNode;
  summaryOpen: boolean;
  onCloseSummary: () => void;
  summaryProps: ComponentProps<typeof SummaryCard>;
}

function ReasoningWorkspace({
  children,
  rightPanelWidth,
  onRightPanelWidthChange,
  promptComposer,
  inspector,
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
        className="flex min-h-0 flex-col gap-3 border-l border-[var(--mw-border)] bg-[var(--mw-page)] px-3 pb-3 pt-3"
        style={{ width: rightPanelWidth }}
      >
        {promptComposer}
        {inspector}
      </aside>
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
    // 1. Prevent default browser drag behaviors
    event.preventDefault();
    
    // 2. Capture the pointer so we don't lose tracking if the mouse moves fast
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    setIsDragging(true);

    const startX = event.clientX;
    const startWidth = width;

    // 3. Temporarily disable text selection across the whole page
    document.body.style.userSelect = "none";

    function handlePointerMove(moveEvent: PointerEvent) {
      const delta = startX - moveEvent.clientX;
      onWidthChange(Math.min(520, Math.max(300, startWidth + delta)));
    }

    function handlePointerUp(upEvent: PointerEvent) {
      handle.releasePointerCapture(upEvent.pointerId);
      setIsDragging(false);
      
      // Restore normal text selection
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
      // Increased width to w-4 for a larger grab area, but kept it visually thin
      className={`relative z-20 flex w-4 cursor-col-resize items-center justify-center transition-colors hover:bg-[var(--mw-node)] ${
        isDragging ? "bg-[var(--mw-node)]" : "bg-transparent"
      }`}
    >
      {/* The thin vertical line */}
      <div 
        className={`absolute inset-y-0 w-px transition-colors ${
          isDragging ? "bg-[var(--mw-accent)]" : "bg-[var(--mw-border)]"
        }`} 
      />
      
      {/* 3-Dot Grip Indicator for visual affordance */}
      <div className="z-10 flex h-6 flex-col justify-between">
        <div className={`h-[3px] w-[3px] rounded-full transition-colors ${isDragging ? "bg-[var(--mw-accent)]" : "bg-[var(--mw-border-strong)]"}`} />
        <div className={`h-[3px] w-[3px] rounded-full transition-colors ${isDragging ? "bg-[var(--mw-accent)]" : "bg-[var(--mw-border-strong)]"}`} />
        <div className={`h-[3px] w-[3px] rounded-full transition-colors ${isDragging ? "bg-[var(--mw-accent)]" : "bg-[var(--mw-border-strong)]"}`} />
      </div>
    </div>
  );

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize reasoning side panel"
      onPointerDown={handlePointerDown}
      className="relative w-2 cursor-col-resize bg-transparent"
    >
      <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-[var(--mw-border)]" />
    </div>
  );
}
