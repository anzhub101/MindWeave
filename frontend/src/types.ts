export type NodeStatus = "pending" | "running" | "completed" | "failed" | "blocked";
export type VerificationStatus = "pending" | "passed" | "failed" | "skipped";
export type TaskStatus = "queued" | "running" | "paused" | "completed" | "failed";

export interface DocumentRecord {
  id: string;
  name: string;
  media_type: string;
  storage_path: string;
  text_path: string;
  sha256: string;
  extracted_text: string;
  metadata: Record<string, unknown>;
}

export interface GraphNode {
  id: string;
  title: string;
  subtitle: string;
  operation_type: string;
  instruction: string;
  success_criteria: string[];
  evaluation_ids: string[];
  priority: number;
  status: NodeStatus;
  verification_status: VerificationStatus;
  depends_on: string[];
  guarded_by: string[];
  next_nodes: string[];
  evidence_refs: string[];
  inputs: Record<string, unknown>;
  output: Record<string, unknown>;
  metadata: {
    layout?: {
      column: number;
      row: number;
    };
    [key: string]: unknown;
  };
  latency_ms: number | null;
}

export interface ReviewDecision {
  timestamp: string;
  node_id: string;
  reviewer: string;
  decision: string;
  comments: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: string;
}

export interface TaskRunResponse {
  task_id: string;
  prompt: string;
  template_id: string;
  program_id: string;
  program_version: string;
  domain: string;
  deterministic: boolean;
  status: TaskStatus;
  created_at: string;
  completed_at: string | null;
  source_documents: DocumentRecord[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  program_blueprint: Record<string, unknown> | null;
  output_schema_definition: Record<string, unknown> | null;
  final_output: Record<string, unknown> | null;
  final_summary: {
    headline: string;
    verdict: string;
    key_points: string[];
    metrics: {
      label: string;
      value: string;
    }[];
  } | null;
  pending_review_node_id: string | null;
  review_history: ReviewDecision[];
  audit_package: Record<string, unknown> | null;
}

export interface TaskRunListItem {
  task_id: string;
  prompt: string;
  status: TaskStatus;
  template_id: string;
  program_id: string;
  domain: string;
  created_at: string;
  completed_at: string | null;
  final_summary: TaskRunResponse["final_summary"];
}
