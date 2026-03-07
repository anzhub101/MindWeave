import { useEffect, useMemo, useState } from "react";
import { fetchAuditPackage, fetchTasks, executeTask, submitReview } from "./api";
import { GraphCanvas } from "./components/GraphCanvas";
import { HeaderBar } from "./components/HeaderBar";
import { InspectorDrawer } from "./components/InspectorDrawer";
import { PromptComposer } from "./components/PromptComposer";
import { Sidebar } from "./components/Sidebar";
import { SummaryCard } from "./components/SummaryCard";
import { mockHistory, mockTask } from "./mockData";
import type { GraphNode, TaskRunListItem, TaskRunResponse } from "./types";

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
  const [prompt, setPrompt] = useState(mockTask.prompt);
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);
  const [task, setTask] = useState<TaskRunResponse>(mockTask);
  const [history, setHistory] = useState<TaskRunListItem[]>(mockHistory);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [offlineDemo, setOfflineDemo] = useState(true);
  const [deterministic, setDeterministic] = useState(true);
  const [autoApproveHumanReview, setAutoApproveHumanReview] = useState(true);
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
            taskLabel={task.final_summary?.headline ?? task.program_id}
            historyCount={history.length}
          />

          {isReasoningView ? (
            <div
              className={`relative grid min-h-0 flex-1 w-full grid-cols-1 gap-4 px-4 pb-4 pt-4 ${
                selectedNode ? "xl:grid-cols-[minmax(0,1fr)_272px]" : ""
              }`}
            >
              <div className="flex min-h-0 min-w-0 flex-col gap-4">
                <GraphCanvas
                  programId={task.program_id}
                  nodes={displayNodes}
                  edges={task.edges}
                  selectedNodeId={selectedNodeId}
                  onSelectNode={(node) => setSelectedNodeId(node.id)}
                />

                <div className="grid gap-3 xl:grid-cols-[minmax(0,1.9fr)_240px]">
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
                  />
                  <SummaryCard
                    status={task.status}
                    summary={task.final_summary}
                    pendingReviewNodeId={task.pending_review_node_id}
                    onApproveReview={() => void handleReview("approved")}
                    onRejectReview={() => void handleReview("rejected")}
                    onExport={handleExport}
                  />
                </div>
              </div>

              {selectedNode ? (
                <InspectorDrawer
                  node={selectedNode}
                  documents={task.source_documents}
                  onClose={() => setSelectedNodeId(null)}
                />
              ) : null}
            </div>
          ) : (
            <div className="relative flex min-h-0 flex-1 bg-transparent" />
          )}
        </main>
      </div>
    </div>
  );
}
