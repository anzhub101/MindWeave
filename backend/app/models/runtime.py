from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.models.artifacts import BudgetSpec


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


class ThoughtRecord(BaseModel):
    id: str
    node_id: str
    summary: str
    content: dict[str, Any]
    evidence_refs: list[str] = Field(default_factory=list)
    depends_on_thoughts: list[str] = Field(default_factory=list)
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
    evidence_refs: list[str] = Field(default_factory=list)


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
    status: NodeStatus = NodeStatus.pending
    verification_status: VerificationStatus = VerificationStatus.pending
    depends_on: list[str] = Field(default_factory=list)
    guarded_by: list[str] = Field(default_factory=list)
    next_nodes: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    spawned_from: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    latency_ms: int | None = None


class GraphReasoningState(BaseModel):
    task_id: str
    prompt: str
    template_id: str
    program_id: str
    program_version: str
    domain: str = "general"
    deterministic: bool
    requirements_reference_path: str | None = None
    status: TaskStatus = TaskStatus.queued
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    source_documents: list[DocumentRecord] = Field(default_factory=list)
    nodes: dict[str, GraphNodeState] = Field(default_factory=dict)
    edges: list[GraphEdge] = Field(default_factory=list)
    thoughts: dict[str, ThoughtRecord] = Field(default_factory=dict)
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
    evidence_refs: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.skipped
    verification_checks: list[str] = Field(default_factory=list)
    thought_summary: str = ""
    llm_usage_tokens: int = 0
    final_output: dict[str, Any] | None = None
    final_summary: dict[str, Any] | None = None
    spawned_nodes: list[GraphNodeState] = Field(default_factory=list)
    cache_hit: bool = False
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
