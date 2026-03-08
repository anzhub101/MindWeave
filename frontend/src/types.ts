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

export interface EvidenceReference {
  id: string;
  document_id: string;
  document_name: string;
  chunk_id: string;
  page: number | null;
  char_start: number | null;
  char_end: number | null;
  retrieval_score: number | null;
  support_level: string;
  citation_mode: string;
  source_type: string;
  text_excerpt: string;
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
  evidence_refs: EvidenceReference[];
  inputs: Record<string, unknown>;
  output: Record<string, unknown>;
  executor_type?: string;
  expansion_contracts?: string[];
  evidence_scope?: Record<string, unknown>;
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
  determinism_mode?: string;
  control_level?: string;
  status: TaskStatus;
  created_at: string;
  completed_at: string | null;
  source_documents: DocumentRecord[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  graph_patch_history?: Array<{
    patch_id: string;
    patch_type: string;
    target_node_id: string | null;
    change_reason: string;
    requested_by: string;
    approved_by: string | null;
    payload: Record<string, unknown>;
    resulting_program_version: string;
    auto_rerun: boolean;
    applied_at: string;
  }>;
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

export interface NodeResolutionResult {
  status: string;
  query: string;
  target_node_id: string | null;
  candidates: string[];
  matched_aliases: string[];
  confidence: number;
  question: string | null;
}

export interface ChangeIntent {
  intent_id: string;
  task_id: string;
  requested_by: string;
  requested_at: string;
  intent_type: string;
  target_node_id: string | null;
  target_scope: string;
  payload: Record<string, unknown>;
  reason: string;
  confidence: number;
  source_text: string;
  status: string;
  resolution: NodeResolutionResult | null;
}

export interface PlannedPatchOperation {
  patch_type: string;
  target_node_id: string | null;
  payload: Record<string, unknown>;
  change_reason: string;
}

export interface PatchProposal {
  proposal_id: string;
  intent_id: string;
  patches: PlannedPatchOperation[];
  summary: string;
  explanation: string;
  affected_node_ids: string[];
  rerun_scope: string;
  risk_level: string;
  requires_approval: boolean;
  planner_confidence: number;
  status: string;
}

export interface PatchValidationResult {
  proposal_id: string;
  status: string;
  errors: string[];
  warnings: string[];
  checked_rules: string[];
  requires_approval: boolean;
  affected_nodes: string[];
}

export interface PlanChangeResponse {
  task_id: string;
  status: string;
  intent: ChangeIntent | null;
  proposal: PatchProposal | null;
  validation: PatchValidationResult | null;
  target_node_resolution: NodeResolutionResult | null;
  clarification_question: string | null;
}
