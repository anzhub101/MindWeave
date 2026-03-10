from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from app.change_planning.intent_models import ChangeIntent, PatchProposal, PatchValidationResult
from app.models.artifacts import AgentSpec, BudgetSpec


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_evidence_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            normalized.append(
                {
                    "id": item,
                    "document_id": item,
                    "document_name": item,
                    "chunk_id": item,
                    "support_level": "direct",
                    "citation_mode": "direct",
                    "source_type": "legacy",
                }
            )
            continue
        if hasattr(item, "model_dump"):
            payload = item.model_dump(mode="json")
            if isinstance(payload, dict):
                item = payload
        if isinstance(item, dict):
            payload = dict(item)
            identifier = str(
                payload.get("id")
                or payload.get("chunk_id")
                or payload.get("document_id")
                or payload.get("document_name")
                or "evidence"
            )
            payload.setdefault("id", identifier)
            payload.setdefault("document_id", str(payload.get("document_id") or payload.get("document_name") or identifier))
            payload.setdefault("document_name", str(payload.get("document_name") or payload["document_id"]))
            payload.setdefault("chunk_id", str(payload.get("chunk_id") or identifier))
            payload.setdefault("support_level", payload.get("support_level") or "direct")
            payload.setdefault("citation_mode", payload.get("citation_mode") or "direct")
            payload.setdefault("source_type", payload.get("source_type") or "retrieved")
            normalized.append(payload)
    return normalized


class NodeStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    blocked = "blocked"


class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"


class VerificationStatus(str, Enum):
    pending = "pending"
    passed = "passed"
    failed = "failed"
    skipped = "skipped"


class DeterminismMode(str, Enum):
    non_deterministic = "non_deterministic"
    best_effort_deterministic = "best_effort_deterministic"
    strict_deterministic = "strict_deterministic"


class ControlLevel(str, Enum):
    exploratory = "exploratory"
    operational = "operational"
    regulated = "regulated"
    strict_audit = "strict_audit"


class ReasoningVisibilityTier(str, Enum):
    summary_trace = "summary_trace"
    structured_reasoning_trace = "structured_reasoning_trace"
    expanded_analytic_trace = "expanded_analytic_trace"


class TraceAccessRole(str, Enum):
    viewer = "viewer"
    reviewer = "reviewer"
    auditor = "auditor"
    admin = "admin"


class ExecutorType(str, Enum):
    llm_operator = "llm_operator"
    tool_operator = "tool_operator"
    agent_operator = "agent_operator"
    human_operator = "human_operator"


class ClaimClassification(str, Enum):
    grounded = "grounded"
    inferred = "inferred"
    calculated = "calculated"
    human_entered = "human_entered"


class EvidenceSupportLevel(str, Enum):
    direct = "direct"
    inferred = "inferred"
    unsupported = "unsupported"
    user_provided = "user_provided"


class DocumentRecord(BaseModel):
    id: str
    name: str
    media_type: str
    storage_path: str
    text_path: str
    sha256: str
    extracted_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: str = "execution"


class EvidenceReference(BaseModel):
    id: str = ""
    document_id: str
    document_name: str = ""
    chunk_id: str
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    retrieval_score: float | None = None
    support_level: EvidenceSupportLevel = EvidenceSupportLevel.direct
    citation_mode: str = "direct"
    source_type: str = "retrieved"
    text_excerpt: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class FindingRecord(BaseModel):
    id: str
    text: str
    support_level: EvidenceSupportLevel = EvidenceSupportLevel.direct
    claim_classification: ClaimClassification = ClaimClassification.grounded
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _coerce_evidence_refs(cls, value: Any) -> list[dict[str, Any]]:
        return _normalize_evidence_list(value)


class EvidenceGraphNode(BaseModel):
    id: str
    kind: str
    label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceGraphEdge(BaseModel):
    source: str
    target: str
    relation: str = "supported_by"
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptTrace(BaseModel):
    trace_id: str
    phase: str
    node_id: str | None = None
    prompt: str
    system_prompt: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    request_payload: dict[str, Any] = Field(default_factory=dict)
    response_payload: dict[str, Any] = Field(default_factory=dict)
    provider: str
    model_id: str
    model_version: str
    provider_fingerprint: str
    endpoint: str | None = None
    prompt_hash: str
    response_hash: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class PlannerEvidenceSource(BaseModel):
    source_id: str
    source_type: str
    label: str
    detail: str = ""
    url: str | None = None


class PlannerCandidateOperation(BaseModel):
    operation: str
    disposition: str = "considered"
    rationale: str
    target_node_id: str | None = None


class PlannerNodeDecision(BaseModel):
    node_id: str
    action: str
    reason: str


class PlannerTrace(BaseModel):
    trace_id: str = Field(default_factory=lambda: f"planner_{uuid4().hex[:10]}")
    summary: str = ""
    graph_shape_reason: str = ""
    evidence_sources_available: list[PlannerEvidenceSource] = Field(default_factory=list)
    web_fallback_used: bool = False
    web_search_queries: list[str] = Field(default_factory=list)
    candidate_graph_operations: list[PlannerCandidateOperation] = Field(default_factory=list)
    node_decisions: list[PlannerNodeDecision] = Field(default_factory=list)
    confidence: float | None = None
    unresolved_gaps: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class GraphPatchRecord(BaseModel):
    patch_id: str = Field(default_factory=lambda: f"patch_{uuid4().hex[:10]}")
    patch_type: str
    target_node_id: str | None = None
    change_reason: str
    requested_by: str
    approved_by: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    resulting_program_version: str
    auto_rerun: bool = True
    applied_at: datetime = Field(default_factory=utcnow)


class GraphVersionRecord(BaseModel):
    version_id: str = Field(default_factory=lambda: f"graph_version_{uuid4().hex[:10]}")
    program_version: str
    blueprint_hash: str
    created_by: str
    reason: str
    patch_id: str | None = None
    parent_program_version: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class PatchDiffRecord(BaseModel):
    patch_id: str
    patch_type: str
    before_program_version: str
    after_program_version: str
    before_blueprint_hash: str
    after_blueprint_hash: str
    added_nodes: list[str] = Field(default_factory=list)
    removed_nodes: list[str] = Field(default_factory=list)
    changed_nodes: list[str] = Field(default_factory=list)
    added_edges: list[str] = Field(default_factory=list)
    removed_edges: list[str] = Field(default_factory=list)
    changed_policy: bool = False
    changed_budget: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class TraceAccessRecord(BaseModel):
    task_id: str
    viewer_id: str
    viewer_role: TraceAccessRole
    requested_tier: ReasoningVisibilityTier
    effective_tier: ReasoningVisibilityTier
    entry_count: int
    accessed_at: datetime = Field(default_factory=utcnow)


class ApprovalState(BaseModel):
    required_approvals: int = 0
    approved_count: int = 0
    pending_approvals: int = 0
    requires_human_review: bool = False
    status: str = "not_required"


class DelegationPolicy(BaseModel):
    enabled: bool = True
    allowed_control_levels: list[ControlLevel] = Field(
        default_factory=lambda: [
            ControlLevel.exploratory,
            ControlLevel.operational,
            ControlLevel.regulated,
        ]
    )
    allowed_program_policies: list[str] = Field(
        default_factory=lambda: ["priority_based", "breadth_first", "cost_aware"]
    )
    complexity_threshold: float = 8.0
    default_child_token_budget: int = 4000
    require_child_summary: bool = True


class ThoughtRecord(BaseModel):
    id: str
    node_id: str
    summary: str
    content: dict[str, Any]
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    depends_on_thoughts: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _coerce_evidence_refs(cls, value: Any) -> list[dict[str, Any]]:
        return _normalize_evidence_list(value)


class GraphDeltaOperation(BaseModel):
    patch_type: str
    target_node_id: str | None = None
    change_reason: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    auto_rerun: bool = False


class GraphDelta(BaseModel):
    delta_id: str = Field(default_factory=lambda: f"delta_{uuid4().hex[:10]}")
    source_node_id: str | None = None
    summary: str = ""
    operations: list[GraphDeltaOperation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class ExecutionLogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=utcnow)
    event: str
    message: str
    node_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class VerificationLogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=utcnow)
    node_id: str
    status: VerificationStatus
    checks: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _coerce_evidence_refs(cls, value: Any) -> list[dict[str, Any]]:
        return _normalize_evidence_list(value)


class ReviewDecision(BaseModel):
    timestamp: datetime = Field(default_factory=utcnow)
    node_id: str
    reviewer: str
    decision: str
    comments: str = ""


class EvaluationLogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=utcnow)
    node_id: str
    evaluation_id: str
    passed: bool
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class SchemaValidationLogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=utcnow)
    node_id: str
    schema_id: str
    phase: str
    passed: bool
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class BudgetUsage(BaseModel):
    nodes_created: int = 0
    tokens_used: int = 0
    runtime_seconds: float = 0.0


class GraphNodeState(BaseModel):
    id: str
    title: str
    subtitle: str
    operation_type: str
    instruction: str = ""
    success_criteria: list[str] = Field(default_factory=list)
    evaluation_ids: list[str] = Field(default_factory=list)
    input_schema_id: str | None = None
    output_schema_id: str | None = None
    priority: int
    executor_type: ExecutorType = ExecutorType.llm_operator
    executor_profile: str | None = None
    agent_spec: AgentSpec | None = None
    max_child_agents: int = 0
    max_recursion_depth: int = 0
    child_token_budget: int = 0
    expansion_contracts: list[str] = Field(default_factory=list)
    delegated_summary_required: bool = False
    required_approvals: int = 0
    approval_state: ApprovalState = Field(default_factory=ApprovalState)
    status: NodeStatus = NodeStatus.pending
    verification_status: VerificationStatus = VerificationStatus.pending
    verification_checks: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    guarded_by: list[str] = Field(default_factory=list)
    next_nodes: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    finding_records: list[FindingRecord] = Field(default_factory=list)
    thought_summary: str = ""
    reasoning_trace: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    prompt_hash: str | None = None
    evaluation_score: float | None = None
    evidence_scope: dict[str, Any] = Field(default_factory=dict)
    delegated_children: list[str] = Field(default_factory=list)
    patch_history: list[str] = Field(default_factory=list)
    spawned_from: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    latency_ms: int | None = None

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _coerce_evidence_refs(cls, value: Any) -> list[dict[str, Any]]:
        return _normalize_evidence_list(value)


class GraphReasoningState(BaseModel):
    task_id: str
    prompt: str
    template_id: str
    program_id: str
    program_version: str
    domain: str = "general"
    deterministic: bool
    determinism_mode: DeterminismMode = DeterminismMode.best_effort_deterministic
    control_level: ControlLevel = ControlLevel.operational
    default_visibility_tier: ReasoningVisibilityTier = ReasoningVisibilityTier.structured_reasoning_trace
    model_id: str = ""
    model_version: str = ""
    provider_fingerprint: str = ""
    execution_endpoint: str | None = None
    prompt_hash: str = ""
    grs_hash: str = ""
    execution_env_hash: str = ""
    reproducibility_hash: str = ""
    requirements_reference_path: str | None = None
    status: TaskStatus = TaskStatus.queued
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    replay_of_task_id: str | None = None
    replay_source_snapshot_label: str | None = None
    source_documents: list[DocumentRecord] = Field(default_factory=list)
    nodes: dict[str, GraphNodeState] = Field(default_factory=dict)
    edges: list[GraphEdge] = Field(default_factory=list)
    execution_sequence: list[str] = Field(default_factory=list)
    thoughts: dict[str, ThoughtRecord] = Field(default_factory=dict)
    evidence_graph_nodes: dict[str, EvidenceGraphNode] = Field(default_factory=dict)
    evidence_graph_edges: list[EvidenceGraphEdge] = Field(default_factory=list)
    prompt_traces: list[PromptTrace] = Field(default_factory=list)
    planner_trace: PlannerTrace | None = None
    graph_patch_history: list[GraphPatchRecord] = Field(default_factory=list)
    graph_version_history: list[GraphVersionRecord] = Field(default_factory=list)
    patch_diff_history: list[PatchDiffRecord] = Field(default_factory=list)
    trace_access_history: list[TraceAccessRecord] = Field(default_factory=list)
    delegation_policy: DelegationPolicy = Field(default_factory=DelegationPolicy)
    change_intents: list[ChangeIntent] = Field(default_factory=list)
    patch_proposals: list[PatchProposal] = Field(default_factory=list)
    patch_validation_history: list[PatchValidationResult] = Field(default_factory=list)
    runtime_graph_deltas: list[GraphDelta] = Field(default_factory=list)
    logs: list[ExecutionLogEntry] = Field(default_factory=list)
    verification_logs: list[VerificationLogEntry] = Field(default_factory=list)
    review_history: list[ReviewDecision] = Field(default_factory=list)
    evaluation_logs: list[EvaluationLogEntry] = Field(default_factory=list)
    schema_validation_logs: list[SchemaValidationLogEntry] = Field(default_factory=list)
    budget_spec: BudgetSpec
    budget_usage: BudgetUsage = Field(default_factory=BudgetUsage)
    program_blueprint: dict[str, Any] | None = None
    output_schema_definition: dict[str, Any] | None = None
    final_output: dict[str, Any] | None = None
    final_summary: dict[str, Any] | None = None
    pending_review_node_id: str | None = None
    graph_build_ms: int | None = None
    scheduler_metrics_ms: list[int] = Field(default_factory=list)
    cache_stats: dict[str, int] = Field(default_factory=lambda: {"hits": 0, "misses": 0})


class NodeExecutionResult(BaseModel):
    output: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.skipped
    verification_checks: list[str] = Field(default_factory=list)
    thought_summary: str = ""
    reasoning_trace: str | None = None
    llm_usage_tokens: int = 0
    prompt_trace: PromptTrace | None = None
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    finding_records: list[FindingRecord] = Field(default_factory=list)
    final_output: dict[str, Any] | None = None
    final_summary: dict[str, Any] | None = None
    graph_delta: GraphDelta | None = None
    spawned_nodes: list[GraphNodeState] = Field(default_factory=list)
    cache_hit: bool = False
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _coerce_evidence_refs(cls, value: Any) -> list[dict[str, Any]]:
        return _normalize_evidence_list(value)
