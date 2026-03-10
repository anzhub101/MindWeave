export type NodeStatus = "pending" | "running" | "completed" | "failed" | "blocked";
export type VerificationStatus = "pending" | "passed" | "failed" | "skipped";
export type TaskStatus = "queued" | "running" | "paused" | "completed" | "failed";
export type DeterminismMode = "non_deterministic" | "best_effort_deterministic" | "strict_deterministic";
export type ControlLevel = "exploratory" | "operational" | "regulated" | "strict_audit";
export type ReasoningVisibilityTier =
  | "summary_trace"
  | "structured_reasoning_trace"
  | "expanded_analytic_trace";
export type TraceAccessRole = "viewer" | "reviewer" | "auditor" | "admin";
export type ClaimClassification = "grounded" | "inferred" | "calculated" | "human_entered";

export interface TemplateSummary {
  template_id: string;
  name: string;
  description: string;
}

export interface DeleteTaskResponse {
  task_id: string;
  deleted: boolean;
}

export interface SkillSummary {
  skill_id: string;
  version: string;
  name: string;
  description: string;
  language: string;
  skill_type: string;
  updated_at: string;
  status: string;
}

export interface SkillArtifact extends SkillSummary {
  entrypoint_filename: string;
  code: string;
  test_input: string;
  notes: string[];
  suggested_node_executor: string;
}

export interface SkillTestResult {
  passed: boolean;
  stdout: string;
  stderr: string;
  exit_code: number;
  command: string[];
}

export interface NodeChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface NodeChatResponse {
  task_id: string;
  node_id: string;
  reply: string;
  tool_results: Array<Record<string, unknown>>;
  suggested_actions: string[];
  model_metadata: Record<string, unknown>;
}

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

export interface FindingRecord {
  id: string;
  text: string;
  support_level: string;
  claim_classification: ClaimClassification;
  evidence_refs: EvidenceReference[];
}

export interface ApprovalState {
  required_approvals: number;
  approved_count: number;
  pending_approvals: number;
  requires_human_review: boolean;
  status: string;
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
  verification_checks?: string[];
  depends_on: string[];
  guarded_by: string[];
  next_nodes: string[];
  evidence_refs: EvidenceReference[];
  finding_records?: FindingRecord[];
  inputs: Record<string, unknown>;
  output: Record<string, unknown>;
  reasoning_trace?: string | null;
  executor_type?: string;
  executor_profile?: string | null;
  max_child_agents?: number;
  max_recursion_depth?: number;
  child_token_budget?: number;
  expansion_contracts?: string[];
  delegated_summary_required?: boolean;
  thought_summary?: string;
  evaluation_score?: number | null;
  approval_state?: ApprovalState;
  evidence_scope?: Record<string, unknown>;
  model_metadata?: Record<string, unknown>;
  delegated_children?: string[];
  patch_history?: string[];
  required_approvals?: number;
  metadata: {
    layout?: {
      column?: number;
      row?: number;
      placement?: string;
      reference_node_id?: string;
      parent_node_id?: string;
      sibling_index?: number;
      sibling_count?: number;
    };
    skill_artifact_id?: string;
    [key: string]: unknown;
  };
  created_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
  latency_ms: number | null;
}

export interface ReviewDecision {
  timestamp: string;
  node_id: string;
  reviewer: string;
  decision: string;
  comments: string;
}

export interface SchemaValidationLogEntry {
  timestamp: string;
  node_id: string;
  schema_id: string;
  phase: string;
  passed: boolean;
  message: string;
  details: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: string;
}

export interface EvidenceGraphNode {
  id: string;
  kind: string;
  label: string;
  metadata: Record<string, unknown>;
}

export interface EvidenceGraphEdge {
  source: string;
  target: string;
  relation: string;
  metadata: Record<string, unknown>;
}

export interface PromptTrace {
  trace_id: string;
  phase: string;
  node_id: string | null;
  prompt: string;
  system_prompt: string | null;
  context: Record<string, unknown>;
  params: Record<string, unknown>;
  request_payload: Record<string, unknown>;
  response_payload: Record<string, unknown>;
  provider: string;
  model_id: string;
  model_version: string;
  provider_fingerprint: string;
  endpoint: string | null;
  prompt_hash: string;
  response_hash: string;
  created_at: string;
}

export interface PlannerEvidenceSource {
  source_id: string;
  source_type: string;
  label: string;
  detail: string;
  url?: string | null;
}

export interface PlannerCandidateOperation {
  operation: string;
  disposition: string;
  rationale: string;
  target_node_id?: string | null;
}

export interface PlannerNodeDecision {
  node_id: string;
  action: string;
  reason: string;
}

export interface PlannerTrace {
  trace_id: string;
  summary: string;
  graph_shape_reason: string;
  evidence_sources_available: PlannerEvidenceSource[];
  web_fallback_used: boolean;
  web_search_queries: string[];
  candidate_graph_operations: PlannerCandidateOperation[];
  node_decisions: PlannerNodeDecision[];
  confidence?: number | null;
  unresolved_gaps: string[];
  created_at: string;
}

export interface GraphPatchRecord {
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
}

export interface GraphPatchRequest {
  patch_type: string;
  target_node_id?: string | null;
  change_reason: string;
  requested_by: string;
  approved_by?: string | null;
  payload?: Record<string, unknown>;
  auto_rerun?: boolean;
}

export interface GraphVersionRecord {
  version_id: string;
  program_version: string;
  blueprint_hash: string;
  created_by: string;
  reason: string;
  patch_id: string | null;
  parent_program_version: string | null;
  created_at: string;
}

export interface PatchDiffRecord {
  patch_id: string;
  patch_type: string;
  before_program_version: string;
  after_program_version: string;
  before_blueprint_hash: string;
  after_blueprint_hash: string;
  added_nodes: string[];
  removed_nodes: string[];
  changed_nodes: string[];
  added_edges: string[];
  removed_edges: string[];
  changed_policy: boolean;
  changed_budget: boolean;
  created_at: string;
}

export interface TraceAccessRecord {
  task_id: string;
  viewer_id: string;
  viewer_role: TraceAccessRole;
  requested_tier: ReasoningVisibilityTier;
  effective_tier: ReasoningVisibilityTier;
  entry_count: number;
  accessed_at: string;
}

export interface TaskRunResponse {
  task_id: string;
  prompt: string;
  template_id: string;
  program_id: string;
  program_version: string;
  domain: string;
  deterministic: boolean;
  determinism_mode?: DeterminismMode;
  control_level?: ControlLevel;
  default_visibility_tier?: ReasoningVisibilityTier;
  status: TaskStatus;
  model_id?: string;
  model_version?: string;
  provider_fingerprint?: string;
  execution_endpoint?: string | null;
  prompt_hash?: string;
  grs_hash?: string;
  execution_env_hash?: string;
  reproducibility_hash?: string;
  created_at: string;
  completed_at: string | null;
  source_documents: DocumentRecord[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  execution_sequence?: string[];
  evidence_graph_nodes?: Record<string, EvidenceGraphNode>;
  evidence_graph_edges?: EvidenceGraphEdge[];
  prompt_traces?: PromptTrace[];
  planner_trace?: PlannerTrace | null;
  graph_patch_history?: GraphPatchRecord[];
  graph_version_history?: GraphVersionRecord[];
  patch_diff_history?: PatchDiffRecord[];
  trace_access_history?: TraceAccessRecord[];
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
  graph_build_ms?: number | null;
  scheduler_metrics_ms?: number[];
  pending_review_node_id: string | null;
  review_history: ReviewDecision[];
  schema_validation_logs?: SchemaValidationLogEntry[];
  audit_package: Record<string, unknown> | null;
}

export interface NodeDetailResponse {
  task_id: string;
  node: GraphNode;
  key_conclusion: string;
  evidence_count: number;
  top_evidence: EvidenceReference[];
  finding_records: FindingRecord[];
  approval_state: ApprovalState;
  approval_reviewers: string[];
  delegated_children: string[];
  delegated_summaries: Array<Record<string, unknown>>;
  patch_history: GraphPatchRecord[];
  reasoning_trace?: string | null;
  technical_details: Record<string, unknown>;
}

export interface TaskRunListItem {
  task_id: string;
  prompt: string;
  status: TaskStatus;
  template_id: string;
  program_id: string;
  domain: string;
  determinism_mode?: DeterminismMode;
  control_level?: ControlLevel;
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

export interface ChangedNodeResponse {
  node_id: string;
  changed_fields: string[];
  left_status: string | null;
  right_status: string | null;
  left_prompt_hash: string | null;
  right_prompt_hash: string | null;
  left_output: Record<string, unknown> | null;
  right_output: Record<string, unknown> | null;
}

export interface ChangedPromptResponse {
  phase: string;
  node_id: string | null;
  left_prompt_hash: string;
  right_prompt_hash: string;
}

export interface ChangedEvidenceResponse {
  node_id: string;
  left_evidence_ids: string[];
  right_evidence_ids: string[];
}

export interface RunDiffResponse {
  left_task_id: string;
  right_task_id: string;
  changed_nodes: ChangedNodeResponse[];
  changed_prompts: ChangedPromptResponse[];
  changed_evidence: ChangedEvidenceResponse[];
  changed_model_metadata: Record<string, unknown>;
  changed_final_output: Record<string, unknown>;
}

export interface ReasoningTraceEntry {
  node_id: string;
  title: string;
  status: string;
  evidence_used: EvidenceReference[];
  conclusion: string;
  claims?: FindingRecord[];
  inputs?: Record<string, unknown>;
  output?: Record<string, unknown>;
  verification_status?: string;
  score?: number | null;
  prompt_hash?: string | null;
  thought_summary?: string;
  expansion_contracts?: string[];
  delegated_from?: string | null;
  model_metadata?: Record<string, unknown>;
}

export interface ReasoningTraceResponse {
  task_id: string;
  tier: ReasoningVisibilityTier;
  entries: ReasoningTraceEntry[];
  metadata: Record<string, unknown>;
}
