from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.artifacts import ArtifactPromotion
from app.models.runtime import (
    DocumentRecord,
    GraphEdge,
    GraphNodeState,
    ReviewDecision,
    SchemaValidationLogEntry,
    TaskStatus,
)


class TemplateSummary(BaseModel):
    template_id: str
    name: str
    description: str


class ArtifactSummary(BaseModel):
    kind: str
    artifact_id: str
    version: str
    name: str
    description: str
    status: str
    source: str
    updated_at: datetime


class ArtifactPayloadRequest(BaseModel):
    artifact_id: str
    version: str
    name: str
    description: str = ""
    payload: dict[str, Any]
    status: str = "active"
    source: str = "user"
    justification: str | None = None


class ArtifactPayloadResponse(ArtifactSummary):
    payload: dict[str, Any]
    created_at: datetime
    justification: str | None = None


class ArtifactPromotionResponse(ArtifactPromotion):
    pass


class PromotionRequest(BaseModel):
    version: str
    justification: str


class ReviewDecisionRequest(BaseModel):
    node_id: str
    reviewer: str
    decision: str
    comments: str = ""


class ReviewDecisionResponse(ReviewDecision):
    task_id: str


class ExperimentRunRequest(BaseModel):
    name: str
    prompts: list[str]
    deterministic: bool = False
    use_sample_data: bool = True
    auto_approve_human_review: bool = True


class ExperimentRunResponse(BaseModel):
    experiment_id: str
    name: str
    status: str
    prompts: list[str]
    task_ids: list[str]
    accuracy_score: float
    runtime_seconds: float
    tokens_used: int
    created_at: datetime


class OptimizationProfileRequest(BaseModel):
    name: str
    evaluation_ids: list[str] = Field(default_factory=list)


class OptimizationRunRequest(BaseModel):
    name: str
    prompts: list[str]
    instruction_prefixes: list[str] = Field(default_factory=lambda: [""])
    policies: list[str] = Field(default_factory=lambda: ["priority_based"])
    evaluation_profiles: list[OptimizationProfileRequest] = Field(
        default_factory=lambda: [OptimizationProfileRequest(name="default", evaluation_ids=[])]
    )
    deterministic: bool = False
    use_sample_data: bool = True
    auto_approve_human_review: bool = True
    promote_best: bool = False


class OptimizationCandidateResult(BaseModel):
    candidate_id: str
    experiment_id: str
    label: str
    instruction_prefix: str
    policy: str
    evaluation_ids: list[str] = Field(default_factory=list)
    accuracy_score: float
    runtime_seconds: float
    tokens_used: int
    score: float
    task_ids: list[str] = Field(default_factory=list)


class OptimizationRunResponse(BaseModel):
    optimization_id: str
    name: str
    status: str
    candidate_results: list[OptimizationCandidateResult]
    best_candidate: OptimizationCandidateResult | None = None
    promoted_artifact_id: str | None = None
    promoted_version: str | None = None
    created_at: datetime


class TaskRunResponse(BaseModel):
    task_id: str
    prompt: str
    template_id: str
    program_id: str
    program_version: str
    domain: str
    deterministic: bool
    status: TaskStatus
    created_at: datetime
    completed_at: datetime | None
    source_documents: list[DocumentRecord]
    nodes: list[GraphNodeState]
    edges: list[GraphEdge]
    program_blueprint: dict[str, Any] | None
    output_schema_definition: dict[str, Any] | None
    final_output: dict[str, Any] | None
    final_summary: dict[str, Any] | None
    graph_build_ms: int | None = None
    scheduler_metrics_ms: list[int] = Field(default_factory=list)
    pending_review_node_id: str | None = None
    review_history: list[ReviewDecision] = Field(default_factory=list)
    schema_validation_logs: list[SchemaValidationLogEntry] = Field(default_factory=list)
    audit_package: dict[str, Any] | None = None


class TaskRunListItem(BaseModel):
    task_id: str
    prompt: str
    status: TaskStatus
    template_id: str
    program_id: str
    domain: str
    created_at: datetime
    completed_at: datetime | None
    final_summary: dict[str, Any] | None
