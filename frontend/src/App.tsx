import { useEffect, useMemo, useState, type ComponentProps, type ReactNode } from "react";
import { LoaderCircle, X } from "lucide-react";
import {
  applyGraphPatch,
  applyPlannedChange,
  chatWithNode,
  changeNodeExecutor,
  deleteTask,
  diffTaskRuns,
  fetchAuditPackage,
  fetchNodeDetail,
  fetchSkill,
  fetchSkills,
  fetchReasoningTrace,
  fetchTask,
  fetchTasks,
  fetchTemplates,
  generateSkill,
  passAndVerifyNode,
  saveSkill,
  saveTemplateArtifact,
  testSkill,
  executeTask,
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
import { SkillsStudio } from "./components/SkillsStudio";
import { SummaryCard } from "./components/SummaryCard";
import { mockHistory, mockSkills, mockTask, mockTemplates } from "./mockData";
import type {
  ControlLevel,
  DeterminismMode,
  GraphPatchRequest,
  GraphNode,
  NodeChatMessage,
  NodeChatResponse,
  NodeDetailResponse,
  PlanChangeResponse,
  ReasoningTraceResponse,
  ReasoningVisibilityTier,
  RunDiffResponse,
  SkillArtifact,
  SkillSummary,
  SkillTestResult,
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

function slugifyTemplateId(value: string) {
  return (
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "saved_template"
  );
}

function inferTemplateKeywords(task: TaskRunResponse) {
  const promptTokens = task.prompt
    .toLowerCase()
    .split(/[^a-z0-9]+/g)
    .filter((token) => token.length > 3);
  return Array.from(new Set([task.domain, ...promptTokens])).slice(0, 8);
}

function slugifySkillId(value: string) {
  return (
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "generated_skill"
  );
}

function defaultEntrypointFilename(language: string) {
  return language === "javascript" ? "main.js" : "main.py";
}

function createBlankSkillDraft(overrides: Partial<SkillArtifact> = {}): SkillArtifact {
  const language = overrides.language ?? "python";
  const name = overrides.name ?? "New Skill";
  return {
    skill_id: overrides.skill_id ?? slugifySkillId(name),
    version: overrides.version ?? "0.1.0",
    name,
    description: overrides.description ?? "",
    language,
    skill_type: overrides.skill_type ?? "script",
    updated_at: overrides.updated_at ?? new Date().toISOString(),
    status: overrides.status ?? "draft",
    entrypoint_filename: overrides.entrypoint_filename ?? defaultEntrypointFilename(language),
    code: overrides.code ?? "",
    test_input: overrides.test_input ?? "",
    notes: overrides.notes ?? [],
    suggested_node_executor: overrides.suggested_node_executor ?? "tool_operator",
  };
}

function nodeChatKey(taskId: string, nodeId: string) {
  return `${taskId}:${nodeId}`;
}

function parseSourceUrls(value: string) {
  return value
    .split(/\n|,/g)
    .map((item) => item.trim())
    .filter(Boolean);
}

function sleep(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

const DEMO_RUNTIME_ENABLED = false;

function nodeLabelList(task: TaskRunResponse, nodeIds: string[]) {
  if (!nodeIds.length) {
    return "none";
  }
  const labels = nodeIds.map((nodeId) => task.nodes.find((node) => node.id === nodeId)?.title ?? nodeId);
  if (labels.length === 1) {
    return labels[0];
  }
  if (labels.length === 2) {
    return `${labels[0]} and ${labels[1]}`;
  }
  return `${labels.slice(0, -1).join(", ")}, and ${labels[labels.length - 1]}`;
}

function isWhyNodeCreatedQuestion(message: string) {
  const normalized = message.toLowerCase();
  return (
    normalized.includes("why was this node created") ||
    normalized.includes("why was this created") ||
    normalized.includes("why does this node exist") ||
    normalized.includes("why this node") ||
    normalized.includes("purpose of this node")
  );
}

function buildDemoNodeCreationAnswer(
  node: GraphNode,
  task: TaskRunResponse,
  nodeDetail: NodeDetailResponse | null,
) {
  const explicitReason =
    typeof node.metadata?.demo_explanation === "string" && node.metadata.demo_explanation.trim()
      ? node.metadata.demo_explanation.trim()
      : node.instruction.replace(/\.$/, "").toLowerCase();
  const parentSummary = node.depends_on.length
    ? `It comes after ${nodeLabelList(task, node.depends_on)} so the graph can use that earlier work as a prerequisite.`
    : "It is at the front of the graph because the audit needs this context before any downstream testing can happen.";
  const childSummary = node.next_nodes.length
    ? `Its output then feeds ${nodeLabelList(task, node.next_nodes)}.`
    : "It is terminal because this is where the graph consolidates the audit conclusion.";
  const evidenceRefs = nodeDetail?.top_evidence?.length ? nodeDetail.top_evidence : node.evidence_refs;
  const evidenceSummary = evidenceRefs.length
    ? `It is primarily anchored to ${evidenceRefs
        .slice(0, 2)
        .map((reference) => reference.document_name || reference.document_id)
        .join(" and ")}.`
    : "It currently has no direct evidence links in the current run.";
  const approvalSummary =
    (node.approval_state?.required_approvals ?? 0) > 0
      ? `It also carries a review checkpoint because ${node.title.toLowerCase()} affects the final audit conclusion.`
      : "";

  return `${node.title} was created to ${explicitReason}. ${parentSummary} ${childSummary} ${evidenceSummary} ${approvalSummary}`.replace(
    /\s+/g,
    " ",
  );
}

function buildDemoCopilotReply(
  node: GraphNode,
  task: TaskRunResponse,
  nodeDetail: NodeDetailResponse | null,
  message: string,
) {
  const normalized = message.toLowerCase();
  const demoParagraph =
    typeof node.metadata?.demo_copilot_paragraph === "string" ? node.metadata.demo_copilot_paragraph.trim() : "";
  const demoSkillResult =
    node.metadata?.demo_skill_result && typeof node.metadata.demo_skill_result === "object"
      ? (node.metadata.demo_skill_result as Record<string, unknown>)
      : null;
  if (
    demoSkillResult &&
    (normalized.includes("run") ||
      normalized.includes("skill") ||
      normalized.includes("tool") ||
      normalized.includes("execute"))
  ) {
    return `${node.title} executed its deployed skill and returned a structured result. ${prettyDemoObject(
      demoSkillResult,
    )} The important audit point is that the graph separates deterministic tool output from judgment: the skill provides the facts, and downstream reasoning evaluates audit impact.`;
  }
  if (demoParagraph && (normalized.includes("deep") || normalized.includes("explain") || normalized.includes("reason"))) {
    return demoParagraph;
  }
  if (isWhyNodeCreatedQuestion(normalized)) {
    return buildDemoNodeCreationAnswer(node, task, nodeDetail);
  }
  if (normalized.includes("evidence") || normalized.includes("support")) {
    const references = (nodeDetail?.top_evidence?.length ? nodeDetail.top_evidence : node.evidence_refs).slice(0, 3);
    if (!references.length) {
      return `${node.title} does not have explicit source links in the current run, so I would treat it as a planning or orchestration node and ask for supporting audit evidence before relying on it.`;
    }
    return `${node.title} is supported by ${references
      .map((reference) => reference.document_name || reference.document_id)
      .join(", ")}. Those sources anchor the node's conclusion and explain why it sits where it does in the audit flow.`;
  }
  if (demoParagraph) {
    return demoParagraph;
  }
  return `${buildDemoNodeCreationAnswer(node, task, nodeDetail)} If you want, ask about the evidence, the downstream impact, or why this node uses ${node.executor_type ?? "llm_operator"} execution.`;
}

function prettyDemoObject(value: Record<string, unknown>) {
  const entries = Object.entries(value).slice(0, 5);
  return entries.map(([key, entry]) => `${key.replace(/[_-]+/g, " ")}: ${JSON.stringify(entry)}`).join("; ");
}

function nextOfflineProgramVersion(version: string) {
  const match = version.match(/^(.*?)-offline\.(\d+)$/);
  if (match) {
    return `${match[1]}-offline.${Number(match[2]) + 1}`;
  }
  return `${version}-offline.1`;
}

function replaceNodeReference(values: string[], fromId: string, toId: string) {
  return values.map((value) => (value === fromId ? toId : value));
}

function appendUnique(values: string[], nextValue: string) {
  return values.includes(nextValue) ? values : [...values, nextValue];
}

function removeEdge(edges: Array<{ source: string; target: string; kind: string }>, source: string, target: string) {
  return edges.filter((edge) => !(edge.source === source && edge.target === target));
}

function upsertEdge(
  edges: Array<{ source: string; target: string; kind: string }>,
  source: string,
  target: string,
  kind: string,
) {
  if (edges.some((edge) => edge.source === source && edge.target === target)) {
    return edges;
  }
  return [...edges, { source, target, kind }];
}

function buildOfflineNode(nodePayload: Record<string, unknown>, fallbackId: string): GraphNode {
  const requiredApprovals = Number(nodePayload.required_approvals ?? 0);
  return {
    id: String(nodePayload.id ?? fallbackId),
    title: String(nodePayload.title ?? "Manual Node"),
    subtitle: String(nodePayload.subtitle ?? "Offline graph edit"),
    operation_type: String(nodePayload.operation_type ?? "analyze"),
    instruction: String(nodePayload.instruction ?? ""),
    success_criteria: Array.isArray(nodePayload.success_criteria)
      ? nodePayload.success_criteria.map((value) => String(value))
      : [],
    evaluation_ids: Array.isArray(nodePayload.evaluation_ids)
      ? nodePayload.evaluation_ids.map((value) => String(value))
      : [],
    priority: Number(nodePayload.priority ?? 100),
    status: "pending",
    verification_status: "pending",
    verification_checks: [],
    depends_on: [],
    guarded_by: [],
    next_nodes: [],
    evidence_refs: [],
    finding_records: [],
    inputs: {},
    output: {},
    executor_type: String(nodePayload.executor_type ?? "llm_operator"),
    executor_profile: nodePayload.executor_profile ? String(nodePayload.executor_profile) : null,
    max_child_agents: Number(nodePayload.max_child_agents ?? 0),
    max_recursion_depth: Number(nodePayload.max_recursion_depth ?? 0),
    child_token_budget: Number(nodePayload.child_token_budget ?? 0),
    expansion_contracts: Array.isArray(nodePayload.expansion_contracts)
      ? nodePayload.expansion_contracts.map((value) => String(value))
      : [],
    delegated_summary_required: Boolean(nodePayload.delegated_summary_required),
    thought_summary: "",
    evaluation_score: null,
    approval_state: {
      required_approvals: requiredApprovals,
      approved_count: 0,
      pending_approvals: requiredApprovals,
      requires_human_review: requiredApprovals > 0,
      status: requiredApprovals > 0 ? "pending" : "not_required",
    },
    evidence_scope:
      nodePayload.evidence_scope && typeof nodePayload.evidence_scope === "object"
        ? (nodePayload.evidence_scope as Record<string, unknown>)
        : {},
    model_metadata: {},
    delegated_children: [],
    patch_history: [],
    required_approvals: requiredApprovals,
    metadata:
      nodePayload.metadata && typeof nodePayload.metadata === "object"
        ? ({ ...(nodePayload.metadata as Record<string, unknown>) } as GraphNode["metadata"])
        : {},
    latency_ms: null,
  };
}

function applyOfflineGraphPatch(task: TaskRunResponse, request: GraphPatchRequest): TaskRunResponse {
  const nextTask = structuredClone(task);
  const payload = (request.payload ?? {}) as Record<string, unknown>;
  const nodePayload = (payload.node ?? {}) as Record<string, unknown>;
  const nodeId = String(nodePayload.id ?? request.target_node_id ?? `manual_${Date.now()}`);
  const newNode = buildOfflineNode(nodePayload, nodeId);
  const nodesById = new Map(nextTask.nodes.map((node) => [node.id, node]));
  const edges = [...nextTask.edges];

  function insertNodeAfter(referenceNodeId: string) {
    const reference = nodesById.get(referenceNodeId);
    if (!reference) {
      throw new Error(`Reference node ${referenceNodeId} was not found.`);
    }
    const downstream = [...reference.next_nodes];
    newNode.depends_on = [referenceNodeId];
    newNode.next_nodes = downstream;
    reference.next_nodes = [newNode.id];
    let nextEdges = upsertEdge(edges, referenceNodeId, newNode.id, "execution");
    for (const targetId of downstream) {
      const target = nodesById.get(targetId);
      if (target) {
        target.depends_on = replaceNodeReference(target.depends_on, referenceNodeId, newNode.id);
      }
      nextEdges = removeEdge(nextEdges, referenceNodeId, targetId);
      nextEdges = upsertEdge(nextEdges, newNode.id, targetId, "execution");
    }
    nextTask.edges = nextEdges;
  }

  function insertNodeBefore(referenceNodeId: string) {
    const reference = nodesById.get(referenceNodeId);
    if (!reference) {
      throw new Error(`Reference node ${referenceNodeId} was not found.`);
    }
    const parents = [...reference.depends_on];
    newNode.depends_on = parents;
    newNode.next_nodes = [referenceNodeId];
    reference.depends_on = [newNode.id];
    let nextEdges = upsertEdge(edges, newNode.id, referenceNodeId, "execution");
    for (const parentId of parents) {
      const parent = nodesById.get(parentId);
      if (parent) {
        parent.next_nodes = replaceNodeReference(parent.next_nodes, referenceNodeId, newNode.id);
      }
      nextEdges = removeEdge(nextEdges, parentId, referenceNodeId);
      nextEdges = upsertEdge(nextEdges, parentId, newNode.id, "execution");
    }
    nextTask.edges = nextEdges;
  }

  function branchFrom(referenceNodeId: string) {
    const reference = nodesById.get(referenceNodeId);
    if (!reference) {
      throw new Error(`Reference node ${referenceNodeId} was not found.`);
    }
    newNode.depends_on = [referenceNodeId];
    reference.next_nodes = appendUnique(reference.next_nodes, newNode.id);
    nextTask.edges = upsertEdge(edges, referenceNodeId, newNode.id, "manual_branch");
  }

  function insertBetween(sourceNodeId: string, targetNodeId: string) {
    const source = nodesById.get(sourceNodeId);
    const target = nodesById.get(targetNodeId);
    if (!source || !target) {
      throw new Error("The requested edge endpoints were not found.");
    }
    newNode.depends_on = [sourceNodeId];
    newNode.next_nodes = [targetNodeId];
    source.next_nodes = replaceNodeReference(source.next_nodes, targetNodeId, newNode.id);
    target.depends_on = replaceNodeReference(target.depends_on, sourceNodeId, newNode.id);
    let nextEdges = removeEdge(edges, sourceNodeId, targetNodeId);
    nextEdges = upsertEdge(nextEdges, sourceNodeId, newNode.id, "execution");
    nextEdges = upsertEdge(nextEdges, newNode.id, targetNodeId, "execution");
    nextTask.edges = nextEdges;
  }

  if (request.patch_type === "add_node") {
    const placement = String(payload.placement ?? "after_node");
    const referenceNodeId = String(payload.reference_node_id ?? request.target_node_id ?? "");
    if (placement === "before_node") {
      insertNodeBefore(referenceNodeId);
    } else if (placement === "branch_from") {
      branchFrom(referenceNodeId);
    } else {
      insertNodeAfter(referenceNodeId);
    }
  } else if (request.patch_type === "insert_node_between") {
    insertBetween(String(payload.source_node_id ?? ""), String(payload.target_node_id ?? request.target_node_id ?? ""));
  } else {
    throw new Error(`Offline mode only supports manual node insertion right now.`);
  }

  nextTask.nodes.push(newNode);
  nextTask.program_version = nextOfflineProgramVersion(nextTask.program_version);
  nextTask.graph_patch_history = [
    ...(nextTask.graph_patch_history ?? []),
    {
      patch_id: `offline_patch_${Date.now()}`,
      patch_type: request.patch_type,
      target_node_id: request.target_node_id ?? null,
      change_reason: request.change_reason,
      requested_by: request.requested_by,
      approved_by: request.approved_by ?? null,
      payload: request.payload ?? {},
      resulting_program_version: nextTask.program_version,
      auto_rerun: request.auto_rerun ?? true,
      applied_at: new Date().toISOString(),
    },
  ];
  return nextTask;
}

function buildTemplatePayload(task: TaskRunResponse) {
  const fallbackPayload = {
    program_id: task.program_id,
    version: task.program_version,
    template_id: task.template_id,
    domain: task.domain,
    goal: task.prompt,
    policy: "priority_based",
    budget: {
      max_nodes: Math.max(task.nodes.length + 4, 12),
      max_tokens: 20000,
      max_runtime_seconds: 600,
    },
    convergence_rule: "verification_passed_and_output_ready",
    output_schema: "task_final_output",
    nodes: task.nodes.map((node) => ({
      id: node.id,
      title: node.title,
      subtitle: node.subtitle,
      operation_type: node.operation_type,
      instruction: node.instruction,
      success_criteria: node.success_criteria,
      evaluation_ids: node.evaluation_ids,
      priority: node.priority,
      executor_type: node.executor_type ?? "llm_operator",
      max_child_agents: node.max_child_agents ?? 0,
      max_recursion_depth: node.max_recursion_depth ?? 0,
      expansion_contracts: node.expansion_contracts ?? [],
      required_approvals: node.required_approvals ?? 0,
      depends_on: node.depends_on,
      next: node.next_nodes,
      guarded_by: node.guarded_by,
      metadata: node.metadata,
      })),
  };
  const blueprint = (task.program_blueprint ? structuredClone(task.program_blueprint) : fallbackPayload) as Record<string, unknown>;
  const metadata =
    blueprint.metadata && typeof blueprint.metadata === "object" && !Array.isArray(blueprint.metadata)
      ? ({ ...blueprint.metadata } as Record<string, unknown>)
      : {};
  if (task.planner_trace) {
    metadata.planner_trace = task.planner_trace;
  }
  blueprint.metadata = metadata;
  return blueprint;
}

export default function App() {
  const [activeItem, setActiveItem] = useState("reasoning");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [activeReasoningModal, setActiveReasoningModal] = useState<"compose" | "workbench" | null>(null);
  const [rightPanelWidth, setRightPanelWidth] = useState(550);
  const [prompt, setPrompt] = useState(mockTask.prompt);
  const [sourceUrlsText, setSourceUrlsText] = useState("");
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);
  const [task, setTask] = useState<TaskRunResponse>(mockTask);
  const [history, setHistory] = useState<TaskRunListItem[]>(mockHistory);
  const [templates, setTemplates] = useState<TemplateSummary[]>(mockTemplates);
  const [skills, setSkills] = useState<SkillSummary[]>(mockSkills);
  const [selectedSkillId, setSelectedSkillId] = useState<string | null>(mockSkills[0]?.skill_id ?? null);
  const [skillDraft, setSkillDraft] = useState<SkillArtifact>(createBlankSkillDraft(mockSkills[0] ?? {}));
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeDetail, setSelectedNodeDetail] = useState<NodeDetailResponse | null>(null);
  const [countdownTime, setCountdownTime] = useState<number | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPlanningChange, setIsPlanningChange] = useState(false);
  const [isApplyingPlannedChange, setIsApplyingPlannedChange] = useState(false);
  const [isLoadingTask, setIsLoadingTask] = useState(false);
  const [isLoadingNodeDetail, setIsLoadingNodeDetail] = useState(false);
  const [isLoadingSkills, setIsLoadingSkills] = useState(false);
  const [isReplayingTask, setIsReplayingTask] = useState(false);
  const [isLoadingTrace, setIsLoadingTrace] = useState(false);
  const [isDiffingRuns, setIsDiffingRuns] = useState(false);
  const [isLoadingTemplates, setIsLoadingTemplates] = useState(false);
  const [isSavingTemplate, setIsSavingTemplate] = useState(false);
  const [isSavingSkill, setIsSavingSkill] = useState(false);
  const [isGeneratingSkill, setIsGeneratingSkill] = useState(false);
  const [isTestingSkill, setIsTestingSkill] = useState(false);
  const [isPassingNode, setIsPassingNode] = useState(false);
  const [isSendingNodeChat, setIsSendingNodeChat] = useState(false);
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [offlineDemo, setOfflineDemo] = useState(false);
  const [determinismMode, setDeterminismMode] = useState<DeterminismMode>("best_effort_deterministic");
  const [controlLevel, setControlLevel] = useState<ControlLevel>("regulated");
  const [autoApproveHumanReview, setAutoApproveHumanReview] = useState(false);
  const [plannedChange, setPlannedChange] = useState<PlanChangeResponse | null>(null);
  const [reasoningTrace, setReasoningTrace] = useState<ReasoningTraceResponse | null>(null);
  const [skillTestResult, setSkillTestResult] = useState<SkillTestResult | null>(null);
  const [skillNotice, setSkillNotice] = useState<{ tone: "info" | "error"; message: string } | null>(null);
  const [nodeChatThreads, setNodeChatThreads] = useState<Record<string, NodeChatMessage[]>>({});
  const [nodeChatResults, setNodeChatResults] = useState<Record<string, NodeChatResponse | null>>({});
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
      if (DEMO_RUNTIME_ENABLED) {
        setHistory(mockHistory);
        setTemplates(mockTemplates);
        setSkills(mockSkills);
        setTask(mockTask);
        setOfflineDemo(true);
        setIsLoadingTemplates(false);
        setIsLoadingSkills(false);
        return;
      }

      setIsLoadingTemplates(true);
      setIsLoadingSkills(true);
      const [tasksResult, templatesResult, skillsResult] = await Promise.allSettled([
        fetchTasks(),
        fetchTemplates(),
        fetchSkills(),
      ]);

      if (cancelled) {
        return;
      }

      if (templatesResult.status === "fulfilled") {
        setTemplates(templatesResult.value);
      } else {
        setTemplates(mockTemplates);
      }

      if (skillsResult.status === "fulfilled") {
        setSkills(skillsResult.value);
      } else {
        setSkills(mockSkills);
      }

      if (tasksResult.status === "fulfilled") {
        setHistory(tasksResult.value);
        setOfflineDemo(false);
        if (tasksResult.value.length > 0) {
          try {
            const latestTask = await fetchTask(tasksResult.value[0].task_id);
            if (!cancelled) {
              syncTaskState(latestTask);
            }
          } catch {
            if (!cancelled) {
              setTask(mockTask);
              setOfflineDemo(true);
            }
          }
        }
      } else {
        setHistory(mockHistory);
        setTask(mockTask);
        setOfflineDemo(true);
      }

      if (!cancelled) {
        setIsLoadingTemplates(false);
        setIsLoadingSkills(false);
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
    if (activeItem !== "reasoning") {
      setActiveReasoningModal(null);
    }
  }, [activeItem]);

  useEffect(() => {
    setNodeChatThreads({});
    setNodeChatResults({});
  }, [task.task_id]);

  useEffect(() => {
    if (skills.some((skill) => skill.skill_id === selectedSkillId)) {
      return;
    }
    const firstSkill = skills[0] ?? null;
    setSelectedSkillId(firstSkill?.skill_id ?? null);
    if (!firstSkill) {
      setSkillDraft(createBlankSkillDraft());
      return;
    }
    if (offlineDemo) {
      const mockSkill = mockSkills.find((skill) => skill.skill_id === firstSkill.skill_id);
      setSkillDraft(createBlankSkillDraft(mockSkill ?? firstSkill));
    } else {
      setSkillDraft(
        createBlankSkillDraft({
          skill_id: firstSkill.skill_id,
          version: firstSkill.version,
          name: firstSkill.name,
          description: firstSkill.description,
          language: firstSkill.language,
          skill_type: firstSkill.skill_type,
          status: firstSkill.status,
          updated_at: firstSkill.updated_at,
        }),
      );
    }
  }, [offlineDemo, selectedSkillId, skills]);

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
  const isSkillsView = activeItem === "skills";
  const pageTitle =
    activeItem === "reasoning"
      ? "Reasoning"
      : activeItem === "dashboard"
        ? "Main Dashboard"
        : activeItem.replace(/-/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
  const pageEyebrow =
    activeItem === "reasoning" ? "Trace Workspace" : activeItem === "dashboard" ? "Keturah AI Spine" : "Workspace";

  function approveDemoNode(nodeId: string, reviewer = "dashboard-user") {
    const timestamp = new Date().toISOString();
    let approvedTitle = nodeId;
    let nextPendingTitle: string | null = null;

    setTask((current) => {
      const nextTask = structuredClone(current);
      const targetNode = nextTask.nodes.find((node) => node.id === nodeId);
      if (!targetNode) {
        return current;
      }

      approvedTitle = targetNode.title;
      const requiredApprovals = Math.max(targetNode.approval_state?.required_approvals ?? targetNode.required_approvals ?? 1, 1);
      targetNode.status = "completed";
      targetNode.verification_status = "passed";
      targetNode.completed_at = timestamp;
      targetNode.required_approvals = requiredApprovals;
      targetNode.approval_state = {
        required_approvals: requiredApprovals,
        approved_count: requiredApprovals,
        pending_approvals: 0,
        requires_human_review: false,
        status: "approved",
      };
      targetNode.verification_checks = [
        ...(targetNode.verification_checks ?? []).filter((check) => !check.toLowerCase().includes("awaiting")),
        `Approved by ${reviewer} during demo review.`,
      ];

      const remainingPending = nextTask.nodes.find((node) => (node.approval_state?.pending_approvals ?? 0) > 0);
      nextTask.pending_review_node_id = remainingPending?.id ?? null;
      nextPendingTitle = remainingPending?.title ?? null;
      nextTask.review_history = [
        ...nextTask.review_history,
        {
          timestamp,
          node_id: nodeId,
          reviewer,
          decision: "approved",
          comments: "Approved in guided replay.",
        },
      ];

      if (!remainingPending) {
        const finalNode = nextTask.nodes.find((node) => node.id === "final_opinion");
        if (finalNode) {
          finalNode.status = "completed";
          finalNode.verification_status = "passed";
          finalNode.completed_at = timestamp;
          finalNode.output = {
            ...finalNode.output,
            package_status: "Ready for export",
            final_opinion: "Qualified if revenue cutoff adjustment is not recorded",
          };
          finalNode.verification_checks = ["Partner gate cleared.", "Final synthesis package is export-ready."];
        }
        nextTask.status = "completed";
        nextTask.completed_at = timestamp;
        nextTask.final_output = {
          ...(nextTask.final_output ?? {}),
          open_approval_gates: [],
          package_status: "Ready for export",
        };
        nextTask.final_summary = {
          headline: "Invisium audit workflow completed",
          verdict: "Qualified draft ready",
          key_points: [
            "All approval gates have been cleared.",
            "Revenue cutoff exceptions remain the key audit finding.",
            "The final report package is ready for export.",
          ],
          metrics: [
            { label: "Nodes", value: String(nextTask.nodes.length) },
            { label: "Approvals", value: "2/2" },
            { label: "Cutoff exposure", value: "$214.5k" },
            { label: "Status", value: "Ready" },
          ],
        };
      } else {
        nextTask.status = "paused";
      }

      return nextTask;
    });

    setSelectedNodeDetail(null);
    setWorkspaceNotice({
      tone: "info",
      message: nextPendingTitle
        ? `Approved ${approvedTitle}. Next approval gate: ${nextPendingTitle}.`
        : `Approved ${approvedTitle}. All approval gates are clear.`,
    });
  }

  function handleToggleSummary() {
    setActiveReasoningModal(null);
    setSummaryOpen((current) => !current);
  }

  function openReasoningModal(modal: "compose" | "workbench") {
    setSummaryOpen(false);
    setActiveReasoningModal(modal);
  }

  function handleOpenCreateGraph() {
    setActiveItem("reasoning");
    setSelectedNodeId(null);
    setSelectedNodeDetail(null);
    openReasoningModal("compose");
  }

  function handleRemoveUploadedFile(index: number) {
    setUploadedFiles((current) => current.filter((_, currentIndex) => currentIndex !== index));
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

    let elapsedSeconds = 0;
    setCountdownTime(elapsedSeconds);
    const interval = setInterval(() => {
      elapsedSeconds += 1;
      setCountdownTime(elapsedSeconds);
    }, 1000);

    try {
      const nextTask = await executeTask(
        prompt,
        uploadedFiles,
        parseSourceUrls(sourceUrlsText),
        determinismMode,
        controlLevel,
        autoApproveHumanReview,
      );
      clearInterval(interval);
      setCountdownTime(null);
      syncTaskState(nextTask);
      setOfflineDemo(false);
      setActiveItem("reasoning");
      setActiveReasoningModal(null);
      setSelectedNodeId(null);
      setSelectedNodeDetail(null);
      setUploadedFiles([]);
      setSourceUrlsText("");
      try {
        const latestHistory = await fetchTasks();
        setHistory(latestHistory);
      } catch {
        // ignore history refresh failure
      }
    } catch {
      clearInterval(interval);
      setCountdownTime(null);
      setTask(structuredClone(mockTask));
      setActiveItem("reasoning");
      setActiveReasoningModal(null);
      setSelectedNodeId(null);
      setSelectedNodeDetail(null);
      setUploadedFiles([]);
      setSourceUrlsText("");
      setOfflineDemo(true);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleReview(decision: "approved" | "rejected") {
    if (offlineDemo && task.pending_review_node_id && decision === "approved") {
      approveDemoNode(task.pending_review_node_id, "summary-reviewer");
      return;
    }
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

  async function handleDeleteTask(taskId: string) {
    if (offlineDemo || taskId === task.task_id) {
      return;
    }
    if (!window.confirm(`Delete run ${taskId}? This cannot be undone.`)) {
      return;
    }
    setDeletingTaskId(taskId);
    try {
      await deleteTask(taskId);
      const latestHistory = await fetchTasks().catch(() => history.filter((item) => item.task_id !== taskId));
      setHistory(latestHistory);
      setWorkspaceNotice({
        tone: "info",
        message: `Deleted run ${taskId}.`,
      });
    } catch (error) {
      setWorkspaceNotice({
        tone: "error",
        message: formatError(error),
      });
    } finally {
      setDeletingTaskId(null);
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

  async function handleChangeNodeExecutor(
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
  ) {
    if (offlineDemo) {
      const timestamp = new Date().toISOString();
      setTask((current) => {
        const nextTask = structuredClone(current);
        const targetNode = nextTask.nodes.find((node) => node.id === nodeId);
        if (!targetNode) {
          return current;
        }
        targetNode.executor_type = payload.executor_type;
        targetNode.executor_profile = payload.executor_profile ?? null;
        targetNode.max_child_agents = payload.max_child_agents ?? 0;
        targetNode.max_recursion_depth = payload.max_recursion_depth ?? 0;
        targetNode.child_token_budget = payload.child_token_budget ?? 0;
        targetNode.delegated_summary_required = payload.delegated_summary_required ?? false;
        targetNode.metadata = {
          ...targetNode.metadata,
          skill_artifact_id: payload.skill_artifact_id ?? undefined,
          demo_execution_applied_at: timestamp,
        };
        targetNode.output = {
          ...targetNode.output,
          demo_execution_mode:
            payload.skill_artifact_id
              ? `Deployed ${payload.skill_artifact_id} with ${payload.executor_type}.`
              : `Updated executor to ${payload.executor_type}.`,
        };
        targetNode.patch_history = [...(targetNode.patch_history ?? []), "offline_executor_update"];
        nextTask.graph_patch_history = [
          ...(nextTask.graph_patch_history ?? []),
          {
            patch_id: `offline_executor_${Date.now()}`,
            patch_type: "change_executor",
            target_node_id: nodeId,
            change_reason: payload.change_reason ?? `Updated execution mode for ${nodeId}.`,
            requested_by: "dashboard-user",
            approved_by: "system-demo",
            payload,
            resulting_program_version: nextTask.program_version,
            auto_rerun: payload.auto_rerun ?? true,
            applied_at: timestamp,
          },
        ];
        return nextTask;
      });
      setSelectedNodeDetail(null);
      setWorkspaceNotice({
        tone: "info",
        message: `Demo execution mode updated for ${nodeId}.`,
      });
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

  async function handleApplyGraphPatch(
    request: GraphPatchRequest,
    focusNodeId: string | null = null,
  ) {
    if (offlineDemo) {
      try {
        const nextTask = applyOfflineGraphPatch(task, request);
        syncTaskState(nextTask);
        setSelectedNodeDetail(null);
        if (focusNodeId && nextTask.nodes.some((node) => node.id === focusNodeId)) {
          setSelectedNodeId(focusNodeId);
        }
        setWorkspaceNotice({
          tone: "info",
          message: `${request.patch_type.replace(/_/g, " ")} applied locally in offline mode.`,
        });
        return;
      } catch (error) {
        setWorkspaceNotice({
          tone: "error",
          message: formatError(error),
        });
        throw error;
      }
    }
    setIsSubmitting(true);
    try {
      const nextTask = await applyGraphPatch(task.task_id, request);
      await refreshTaskGraph(nextTask.task_id, focusNodeId ?? selectedNodeId);
      const latestHistory = await fetchTasks().catch(() => history);
      setHistory(latestHistory);
      setWorkspaceNotice({
        tone: "info",
        message: `${request.patch_type.replace(/_/g, " ")} applied to ${nextTask.task_id}.`,
      });
    } catch (error) {
      setWorkspaceNotice({
        tone: "error",
        message: formatError(error),
      });
      throw error;
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handlePassAndVerifyNode(nodeId: string) {
    if (offlineDemo) {
      approveDemoNode(nodeId, "node-inspector");
      return;
    }
    setIsPassingNode(true);
    try {
      const nextTask = await passAndVerifyNode(task.task_id, nodeId, "dashboard-user");
      await refreshTaskGraph(nextTask.task_id, nodeId);
      const latestHistory = await fetchTasks().catch(() => history);
      setHistory(latestHistory);
      setWorkspaceNotice({
        tone: "info",
        message: `Pass and verify recorded for ${nodeId}.`,
      });
    } catch (error) {
      setWorkspaceNotice({
        tone: "error",
        message: formatError(error),
      });
    } finally {
      setIsPassingNode(false);
    }
  }

  async function handleSaveAsTemplate() {
    if (offlineDemo) {
      setWorkspaceNotice({
        tone: "error",
        message: "Template saving is unavailable while the UI is using offline demo data.",
      });
      return;
    }

    const defaultName = `${task.program_id.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase())} Template`;
    const name = window.prompt("Template name", defaultName)?.trim();
    if (!name) {
      return;
    }

    const description =
      window.prompt("Template description", `Saved from task ${task.task_id}.`)?.trim() ||
      `Saved from task ${task.task_id}.`;
    const stamp = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
    const artifactId = `${slugifyTemplateId(name)}_${stamp}`.slice(0, 120);

    setIsSavingTemplate(true);
    try {
      await saveTemplateArtifact({
        artifact_id: artifactId,
        version: task.program_version,
        name,
        description,
        payload: {
          template_id: artifactId,
          name,
          description,
          program_id: task.program_id,
          program_version: task.program_version,
          keywords: inferTemplateKeywords(task),
          reasoning_program: buildTemplatePayload(task),
          source_task_id: task.task_id,
          determinism_mode: task.determinism_mode ?? "best_effort_deterministic",
          control_level: task.control_level ?? "operational",
        },
      });
      const availableTemplates = await fetchTemplates().catch(() => templates);
      setTemplates(availableTemplates);
      setWorkspaceNotice({
        tone: "info",
        message: `Saved ${name} as template ${artifactId}.`,
      });
    } catch (error) {
      setWorkspaceNotice({
        tone: "error",
        message: formatError(error),
      });
    } finally {
      setIsSavingTemplate(false);
    }
  }

  async function handleSelectSkill(nextSkillId: string) {
    setSelectedSkillId(nextSkillId);
    setSkillTestResult(null);
    setSkillNotice(null);
    if (offlineDemo) {
      const mockSkill = mockSkills.find((skill) => skill.skill_id === nextSkillId);
      setSkillDraft(createBlankSkillDraft(mockSkill ?? {}));
      return;
    }
    setIsLoadingSkills(true);
    try {
      const skill = await fetchSkill(nextSkillId);
      setSkillDraft(createBlankSkillDraft(skill));
    } catch (error) {
      setSkillNotice({
        tone: "error",
        message: formatError(error),
      });
    } finally {
      setIsLoadingSkills(false);
    }
  }

  function handleCreateSkillDraft() {
    setSelectedSkillId(null);
    setSkillTestResult(null);
    setSkillNotice(null);
    setSkillDraft(createBlankSkillDraft());
  }

  async function handleGenerateSkillDraft(promptText: string, language: string, skillType: string) {
    if (!promptText.trim()) {
      return;
    }
    setIsGeneratingSkill(true);
    try {
      if (offlineDemo) {
        const generated = createBlankSkillDraft({
          skill_id: slugifySkillId(skillDraft.name || "generated_skill"),
          name: skillDraft.name || "Generated Skill",
          description: promptText,
          language,
          skill_type: skillType,
          entrypoint_filename: defaultEntrypointFilename(language),
          code:
            language === "javascript"
              ? "const fs = require('fs');\nconst raw = fs.readFileSync(0, 'utf8') || '{}';\nconst payload = JSON.parse(raw);\nconsole.log(JSON.stringify({ ok: true, payload }));\n"
              : "import json\nimport sys\n\nraw = sys.stdin.read() or '{}'\npayload = json.loads(raw)\nprint(json.dumps({'ok': True, 'payload': payload}))\n",
          notes: ["Offline demo generated a scaffold. Use a live backend session to synthesize a tailored skill."],
        });
        setSkillDraft(generated);
        setSkillNotice({
          tone: "info",
          message: "Generated an offline scaffold skill draft.",
        });
        return;
      }
      const generated = await generateSkill({
        prompt: promptText,
        language,
        skill_type: skillType,
        existing_code: skillDraft.code,
      });
      setSelectedSkillId(generated.skill_id);
      setSkillDraft(createBlankSkillDraft(generated));
      setSkillNotice({
        tone: "info",
        message: `Generated a draft for ${generated.name}.`,
      });
    } catch (error) {
      setSkillNotice({
        tone: "error",
        message: formatError(error),
      });
    } finally {
      setIsGeneratingSkill(false);
    }
  }

  async function handleTestSkillDraft() {
    if (!skillDraft.code.trim()) {
      return;
    }
    setIsTestingSkill(true);
    try {
      const result = await testSkill({
        language: skillDraft.language,
        entrypoint_filename: skillDraft.entrypoint_filename,
        code: skillDraft.code,
        test_input: skillDraft.test_input,
      });
      setSkillTestResult(result);
      setSkillNotice({
        tone: result.passed ? "info" : "error",
        message: result.passed ? "Skill test passed." : "Skill test failed. Review stdout and stderr below.",
      });
    } catch (error) {
      setSkillNotice({
        tone: "error",
        message: formatError(error),
      });
      setSkillTestResult(null);
    } finally {
      setIsTestingSkill(false);
    }
  }

  async function handleSaveSkillDraft() {
    if (!skillDraft.code.trim()) {
      return;
    }
    setIsSavingSkill(true);
    try {
      const persisted = await saveSkill({
        skill_id: skillDraft.skill_id || slugifySkillId(skillDraft.name),
        version: skillDraft.version || "0.1.0",
        name: skillDraft.name || "Generated Skill",
        description: skillDraft.description,
        language: skillDraft.language,
        skill_type: skillDraft.skill_type,
        entrypoint_filename: skillDraft.entrypoint_filename,
        code: skillDraft.code,
        test_input: skillDraft.test_input,
      });
      const latestSkills = await fetchSkills().catch(() => skills);
      setSkills(latestSkills);
      setSelectedSkillId(persisted.skill_id);
      setSkillDraft(createBlankSkillDraft(persisted));
      setSkillNotice({
        tone: "info",
        message: `Saved skill ${persisted.skill_id}.`,
      });
    } catch (error) {
      setSkillNotice({
        tone: "error",
        message: formatError(error),
      });
    } finally {
      setIsSavingSkill(false);
    }
  }

  async function handleSendNodeChat(nodeId: string, message: string) {
    const trimmedMessage = message.trim();
    if (!trimmedMessage) {
      return;
    }
    const node = task.nodes.find((entry) => entry.id === nodeId);
    if (!node) {
      return;
    }
    const relevantNodeDetail =
      selectedNodeDetail && selectedNodeDetail.node.id === nodeId && selectedNodeDetail.task_id === task.task_id
        ? selectedNodeDetail
        : null;
    const key = nodeChatKey(task.task_id, nodeId);
    const priorHistory = nodeChatThreads[key] ?? [];
    const nextHistory = [...priorHistory, { role: "user", content: trimmedMessage } satisfies NodeChatMessage];
    setNodeChatThreads((current) => ({
      ...current,
      [key]: nextHistory,
    }));
    setIsSendingNodeChat(true);
    const minimumResponseDelayMs = 900 + Math.round(Math.random() * 450);
    const responseStartedAt = Date.now();
    try {
      if (offlineDemo) {
        const reply = buildDemoCopilotReply(node, task, relevantNodeDetail, trimmedMessage);
        const demoSkillResult =
          node.metadata?.demo_skill_result && typeof node.metadata.demo_skill_result === "object"
            ? (node.metadata.demo_skill_result as Record<string, unknown>)
            : null;
        const usedSkill =
          demoSkillResult &&
          /run|skill|tool|execute/i.test(trimmedMessage)
            ? [{ tool: String(demoSkillResult.tool ?? node.metadata.skill_artifact_id ?? "demo_skill"), ...demoSkillResult }]
            : [];
        const remainingDelay = minimumResponseDelayMs - (Date.now() - responseStartedAt);
        if (remainingDelay > 0) {
          await sleep(remainingDelay);
        }
        setNodeChatThreads((current) => ({
          ...current,
          [key]: [...nextHistory, { role: "assistant", content: reply }],
        }));
        setNodeChatResults((current) => ({
          ...current,
          [key]: {
            task_id: task.task_id,
            node_id: nodeId,
            reply,
            tool_results: usedSkill,
            suggested_actions: [
              "Why was this node created?",
              "What evidence supports this node?",
              node.metadata?.demo_skill_result ? "Run the deployed skill" : `Explain ${node.title} in depth`,
              `What happens after ${node.title}?`,
            ],
            model_metadata: { provider: "local_replay" },
          },
        }));
        return;
      }
      const response = await chatWithNode(task.task_id, nodeId, trimmedMessage, priorHistory);
      const remainingDelay = minimumResponseDelayMs - (Date.now() - responseStartedAt);
      if (remainingDelay > 0) {
        await sleep(remainingDelay);
      }
      setNodeChatThreads((current) => ({
        ...current,
        [key]: [...nextHistory, { role: "assistant", content: response.reply }],
      }));
      setNodeChatResults((current) => ({
        ...current,
        [key]: response,
      }));
    } catch (error) {
      setWorkspaceNotice({
        tone: "error",
        message: formatError(error),
      });
      setNodeChatThreads((current) => ({
        ...current,
        [key]: [...nextHistory.slice(0, -1)],
      }));
    } finally {
      setIsSendingNodeChat(false);
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
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(86,168,255,0.10),_transparent_38%),radial-gradient(circle_at_bottom,_rgba(219,112,91,0.08),_transparent_30%)]" />
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
                  <button
                    type="button"
                    onClick={() => void handleSaveAsTemplate()}
                    disabled={isSavingTemplate || offlineDemo}
                    className="flex h-11 items-center rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 text-sm text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-55"
                  >
                    {isSavingTemplate ? "Saving..." : "Save As Template"}
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
                    {!selectedNode ? (
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
                    ) : null}
                    {selectedNode ? (
                      <InspectorDrawer
                        node={selectedNode}
                        nodeDetail={selectedNodeDetail}
                        isLoading={isLoadingNodeDetail}
                        isUpdatingExecutor={isSubmitting}
                        isPassing={isPassingNode}
                        isChatting={isSendingNodeChat}
                        chatMessages={nodeChatThreads[nodeChatKey(task.task_id, selectedNode.id)] ?? []}
                        chatResponse={nodeChatResults[nodeChatKey(task.task_id, selectedNode.id)] ?? null}
                        availableSkills={skills}
                        onChangeExecutor={handleChangeNodeExecutor}
                        onPassAndVerifyNode={handlePassAndVerifyNode}
                        onSendChat={handleSendNodeChat}
                        onOpenSkillsWorkspace={() => setActiveItem("skills")}
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
                    canEditGraph
                    isApplyingPatch={isSubmitting}
                    onApplyGraphPatch={handleApplyGraphPatch}
                    onSelectNode={(node) => {
                      setSelectedNodeId(node.id);
                      setSelectedNodeDetail(null);
                    }}
                    onPassNode={(node) => void handlePassAndVerifyNode(node.id)}
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
                  sourceUrls={sourceUrlsText}
                  onSourceUrlsChange={setSourceUrlsText}
                  onSubmit={handleSubmit}
                  onFileSelect={setUploadedFiles}
                  onRemoveFile={handleRemoveUploadedFile}
                  determinismMode={determinismMode}
                  onDeterminismModeChange={setDeterminismMode}
                  controlLevel={controlLevel}
                  onControlLevelChange={setControlLevel}
                  autoApproveHumanReview={autoApproveHumanReview}
                  onAutoApproveHumanReviewChange={setAutoApproveHumanReview}
                  files={uploadedFiles}
                  isSubmitting={isSubmitting}
                  offlineDemo={false}
                  countdownTime={countdownTime}
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
              {isSkillsView ? (
                <SkillsStudio
                  skills={skills}
                  draft={skillDraft}
                  selectedSkillId={selectedSkillId}
                  isLoadingSkills={isLoadingSkills}
                  isGenerating={isGeneratingSkill}
                  isTesting={isTestingSkill}
                  isSaving={isSavingSkill}
                  testResult={skillTestResult}
                  notice={skillNotice}
                  onSelectSkill={handleSelectSkill}
                  onCreateDraft={handleCreateSkillDraft}
                  onDraftChange={(patch) =>
                    setSkillDraft((current) =>
                      createBlankSkillDraft({
                        ...current,
                        ...patch,
                        entrypoint_filename:
                          patch.language && current.entrypoint_filename === defaultEntrypointFilename(current.language)
                            ? defaultEntrypointFilename(patch.language)
                            : patch.entrypoint_filename ?? current.entrypoint_filename,
                      }),
                    )
                  }
                  onGenerate={handleGenerateSkillDraft}
                  onTest={handleTestSkillDraft}
                  onSave={handleSaveSkillDraft}
                />
              ) : (
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
                  onCreateGraph={handleOpenCreateGraph}
                  onDeleteTask={handleDeleteTask}
                  deletingTaskId={deletingTaskId}
                  onNavigateReasoning={() => setActiveItem("reasoning")}
                />
              )}
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
            className="relative z-10 flex h-[80vh] w-[min(80vw,1440px)] min-w-[min(960px,96vw)] flex-col overflow-hidden rounded-[28px] border border-[var(--mw-border)] bg-[var(--mw-page)] shadow-[0_40px_120px_rgba(0,0,0,0.40)]"          >
            <SummaryCard {...summaryProps} />
          </div>
        </div>
      ) : null}

      <div className="min-h-0 min-w-0 flex-1 px-4 pb-4 pt-4">{children}</div>
      <PanelResizeHandle width={rightPanelWidth} onWidthChange={onRightPanelWidthChange} />
      <aside
        className="min-h-0 border-l border-[var(--mw-border)] bg-[var(--mw-page)] px-3 pb-3 pt-3"
        style={{ width: rightPanelWidth, zoom: rightPanelWidth < 450 ? 0.8 : 1 }}
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
            <div className="mt-1 font-sans text-[28px] font-semibold leading-none text-[var(--mw-text)]">{title}</div>
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
      onWidthChange(Math.min(550, Math.max(300, startWidth + delta)));
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
