from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from app.change_planning.intent_models import ChangeIntent, PatchProposal, PatchValidationResult
from app.models.artifacts import BudgetSpec


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


class ExecutorType(str, Enum):
    llm_operator = "llm_operator"
    tool_operator = "tool_operator"
    agent_operator = "agent_operator"
    human_operator = "human_operator"


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
    max_child_agents: int = 0
    max_recursion_depth: int = 0
    expansion_contracts: list[str] = Field(default_factory=list)
    required_approvals: int = 0
    status: NodeStatus = NodeStatus.pending
    verification_status: VerificationStatus = VerificationStatus.pending
    depends_on: list[str] = Field(default_factory=list)
    guarded_by: list[str] = Field(default_factory=list)
    next_nodes: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    prompt_hash: str | None = None
    evaluation_score: float | None = None
    evidence_scope: dict[str, Any] = Field(default_factory=dict)
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
    graph_patch_history: list[GraphPatchRecord] = Field(default_factory=list)
    change_intents: list[ChangeIntent] = Field(default_factory=list)
    patch_proposals: list[PatchProposal] = Field(default_factory=list)
    patch_validation_history: list[PatchValidationResult] = Field(default_factory=list)
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
    llm_usage_tokens: int = 0
    prompt_trace: PromptTrace | None = None
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    finding_records: list[FindingRecord] = Field(default_factory=list)
    final_output: dict[str, Any] | None = None
    final_summary: dict[str, Any] | None = None
    spawned_nodes: list[GraphNodeState] = Field(default_factory=list)
    cache_hit: bool = False
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _coerce_evidence_refs(cls, value: Any) -> list[dict[str, Any]]:
        return _normalize_evidence_list(value)
