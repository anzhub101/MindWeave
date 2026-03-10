import type {
  ControlLevel,
  DeleteTaskResponse,
  DeterminismMode,
  GraphPatchRequest,
  NodeDetailResponse,
  NodeChatMessage,
  NodeChatResponse,
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

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

async function ensureOk(response: Response): Promise<Response> {
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response;
}

export async function executeTask(
  prompt: string,
  files: File[],
  sourceUrls: string[],
  deterministicMode: DeterminismMode,
  controlLevel: ControlLevel,
  autoApproveHumanReview: boolean,
): Promise<TaskRunResponse> {
  const formData = new FormData();
  formData.set("prompt", prompt);
  formData.set("deterministic", String(deterministicMode !== "non_deterministic"));
  formData.set("determinism_mode", deterministicMode);
  formData.set("control_level", controlLevel);
  formData.set("auto_approve_human_review", String(autoApproveHumanReview));
  formData.set("use_sample_data", "false");
  formData.set("source_urls", JSON.stringify(sourceUrls));
  files.forEach((file) => formData.append("files", file));

  const response = await fetch(`${API_BASE}/tasks/execute`, {
    method: "POST",
    body: formData,
  });

  return ensureOk(response).then((result) => result.json());
}

export async function fetchTasks(): Promise<TaskRunListItem[]> {
  const response = await fetch(`${API_BASE}/tasks`);
  return ensureOk(response).then((result) => result.json());
}

export async function deleteTask(taskId: string): Promise<DeleteTaskResponse> {
  const response = await fetch(`${API_BASE}/tasks/${taskId}`, {
    method: "DELETE",
  });
  return ensureOk(response).then((result) => result.json());
}

export async function fetchTemplates(): Promise<TemplateSummary[]> {
  const response = await fetch(`${API_BASE}/templates`);
  return ensureOk(response).then((result) => result.json());
}

export async function fetchSkills(): Promise<SkillSummary[]> {
  const response = await fetch(`${API_BASE}/skills`);
  return ensureOk(response).then((result) => result.json());
}

export async function fetchSkill(skillId: string): Promise<SkillArtifact> {
  const response = await fetch(`${API_BASE}/skills/${skillId}`);
  return ensureOk(response).then((result) => result.json());
}

export async function generateSkill(payload: {
  prompt: string;
  language: string;
  skill_type: string;
  existing_code?: string;
}): Promise<SkillArtifact> {
  const response = await fetch(`${API_BASE}/skills/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      existing_code: "",
      ...payload,
    }),
  });
  return ensureOk(response).then((result) => result.json());
}

export async function saveSkill(payload: {
  skill_id: string;
  version: string;
  name: string;
  description: string;
  language: string;
  skill_type: string;
  entrypoint_filename: string;
  code: string;
  test_input?: string;
}): Promise<SkillArtifact> {
  const response = await fetch(`${API_BASE}/skills`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      test_input: "",
      ...payload,
    }),
  });
  return ensureOk(response).then((result) => result.json());
}

export async function testSkill(payload: {
  language: string;
  entrypoint_filename: string;
  code: string;
  test_input?: string;
  args?: string[];
}): Promise<SkillTestResult> {
  const response = await fetch(`${API_BASE}/skills/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      test_input: "",
      args: [],
      ...payload,
    }),
  });
  return ensureOk(response).then((result) => result.json());
}

export async function saveTemplateArtifact(payload: {
  artifact_id: string;
  version: string;
  name: string;
  description: string;
  payload: Record<string, unknown>;
  status?: string;
  source?: string;
  justification?: string | null;
}): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/design/template`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      status: "active",
      source: "user",
      justification: null,
      ...payload,
    }),
  });
  return ensureOk(response).then((result) => result.json());
}

export async function fetchTask(taskId: string): Promise<TaskRunResponse> {
  const response = await fetch(`${API_BASE}/tasks/${taskId}`);
  return ensureOk(response).then((result) => result.json());
}

export async function fetchNodeDetail(taskId: string, nodeId: string): Promise<NodeDetailResponse> {
  const response = await fetch(`${API_BASE}/tasks/${taskId}/nodes/${nodeId}`);
  return ensureOk(response).then((result) => result.json());
}

export async function fetchAuditPackage(taskId: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/tasks/${taskId}/audit`);
  return ensureOk(response).then((result) => result.json());
}

export async function submitReview(
  taskId: string,
  nodeId: string,
  decision: "approved" | "rejected",
  reviewer = "dashboard-user",
  comments = "",
): Promise<TaskRunResponse> {
  const response = await fetch(`${API_BASE}/tasks/${taskId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      node_id: nodeId,
      reviewer,
      decision,
      comments,
    }),
  });
  return ensureOk(response).then((result) => result.json());
}

export async function planTaskChange(
  taskId: string,
  requestText: string,
  requestedBy: string,
  selectedNodeId: string | null,
): Promise<PlanChangeResponse> {
  const response = await fetch(`${API_BASE}/tasks/${taskId}/plan-change`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      request_text: requestText,
      requested_by: requestedBy,
      selected_node_id: selectedNodeId,
    }),
  });
  return ensureOk(response).then((result) => result.json());
}

export async function planNodeChange(
  taskId: string,
  nodeId: string,
  requestText: string,
  requestedBy: string,
): Promise<PlanChangeResponse> {
  const response = await fetch(`${API_BASE}/tasks/${taskId}/nodes/${nodeId}/plan-change`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      request_text: requestText,
      requested_by: requestedBy,
    }),
  });
  return ensureOk(response).then((result) => result.json());
}

export async function applyPlannedChange(
  taskId: string,
  proposalId: string,
  approvedBy: string,
  autoRerun: boolean,
): Promise<TaskRunResponse> {
  const response = await fetch(`${API_BASE}/tasks/${taskId}/apply-planned-change`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      proposal_id: proposalId,
      approved_by: approvedBy || null,
      auto_rerun: autoRerun,
    }),
  });
  return ensureOk(response).then((result) => result.json());
}

export async function applyGraphPatch(
  taskId: string,
  request: GraphPatchRequest,
): Promise<TaskRunResponse> {
  const response = await fetch(`${API_BASE}/tasks/${taskId}/patch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      auto_rerun: true,
      payload: {},
      ...request,
    }),
  });
  return ensureOk(response).then((result) => result.json());
}

export async function changeNodeExecutor(
  taskId: string,
  nodeId: string,
  payload: {
    executor_type: string;
    executor_profile?: string | null;
    skill_artifact_id?: string | null;
    max_child_agents?: number;
    max_recursion_depth?: number;
    child_token_budget?: number;
    delegated_summary_required?: boolean;
    requested_by?: string;
    approved_by?: string | null;
    change_reason?: string;
    instruction_note?: string;
    auto_rerun?: boolean;
  },
): Promise<TaskRunResponse> {
  const response = await fetch(`${API_BASE}/tasks/${taskId}/nodes/${nodeId}/change-executor`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      requested_by: "dashboard-user",
      auto_rerun: true,
      max_child_agents: 0,
      max_recursion_depth: 0,
      child_token_budget: 0,
      delegated_summary_required: false,
      ...payload,
    }),
  });
  return ensureOk(response).then((result) => result.json());
}

export async function passAndVerifyNode(
  taskId: string,
  nodeId: string,
  reviewer = "dashboard-user",
  comments = "",
  resumeExecution = true,
): Promise<TaskRunResponse> {
  const response = await fetch(`${API_BASE}/tasks/${taskId}/nodes/${nodeId}/pass-verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      reviewer,
      comments,
      resume_execution: resumeExecution,
    }),
  });
  return ensureOk(response).then((result) => result.json());
}

export async function chatWithNode(
  taskId: string,
  nodeId: string,
  message: string,
  history: NodeChatMessage[],
): Promise<NodeChatResponse> {
  const response = await fetch(`${API_BASE}/tasks/${taskId}/nodes/${nodeId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      history,
    }),
  });
  return ensureOk(response).then((result) => result.json());
}

export async function replayTask(
  taskId: string,
  autoApproveHumanReview: boolean,
): Promise<TaskRunResponse> {
  const response = await fetch(`${API_BASE}/tasks/${taskId}/replay`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      resume_from_snapshot: false,
      auto_approve_human_review: autoApproveHumanReview,
    }),
  });
  return ensureOk(response).then((result) => result.json());
}

export async function fetchReasoningTrace(
  taskId: string,
  tier: ReasoningVisibilityTier,
  viewerRole: TraceAccessRole,
  viewerId: string,
): Promise<ReasoningTraceResponse> {
  const query = new URLSearchParams({
    tier,
    viewer_role: viewerRole,
    viewer_id: viewerId,
  });
  const response = await fetch(`${API_BASE}/tasks/${taskId}/trace?${query.toString()}`);
  return ensureOk(response).then((result) => result.json());
}

export async function diffTaskRuns(
  leftTaskId: string,
  rightTaskId: string,
): Promise<RunDiffResponse> {
  const response = await fetch(`${API_BASE}/tasks/diff`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      left_task_id: leftTaskId,
      right_task_id: rightTaskId,
    }),
  });
  return ensureOk(response).then((result) => result.json());
}
