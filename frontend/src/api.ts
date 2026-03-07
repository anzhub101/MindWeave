import type { TaskRunListItem, TaskRunResponse } from "./types";

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
  deterministic: boolean,
  autoApproveHumanReview: boolean,
): Promise<TaskRunResponse> {
  const formData = new FormData();
  formData.set("prompt", prompt);
  formData.set("deterministic", String(deterministic));
  formData.set("auto_approve_human_review", String(autoApproveHumanReview));
  formData.set("use_sample_data", files.length === 0 ? "true" : "false");
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
