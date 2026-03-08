from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.artifacts import ArtifactPromotion
from app.change_planning.intent_models import ChangeIntent, NodeResolutionResult, PatchProposal, PatchValidationResult
from app.models.runtime import (
    ControlLevel,
    DeterminismMode,
    DocumentRecord,
    EvidenceGraphEdge,
    EvidenceGraphNode,
    GraphPatchRecord,
    GraphEdge,
    GraphNodeState,
    PromptTrace,
    ReasoningVisibilityTier,
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
    determinism_mode: DeterminismMode | None = None
    control_level: ControlLevel = ControlLevel.operational
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
    determinism_mode: DeterminismMode | None = None
    control_level: ControlLevel = ControlLevel.operational
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
    determinism_mode: DeterminismMode
    control_level: ControlLevel
    default_visibility_tier: ReasoningVisibilityTier
    status: TaskStatus
    model_id: str
    model_version: str
    provider_fingerprint: str
    execution_endpoint: str | None
    prompt_hash: str
    grs_hash: str
    execution_env_hash: str
    reproducibility_hash: str
    created_at: datetime
    completed_at: datetime | None
    source_documents: list[DocumentRecord]
    nodes: list[GraphNodeState]
    edges: list[GraphEdge]
    execution_sequence: list[str] = Field(default_factory=list)
    evidence_graph_nodes: dict[str, EvidenceGraphNode] = Field(default_factory=dict)
    evidence_graph_edges: list[EvidenceGraphEdge] = Field(default_factory=list)
    prompt_traces: list[PromptTrace] = Field(default_factory=list)
    graph_patch_history: list[GraphPatchRecord] = Field(default_factory=list)
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
    determinism_mode: DeterminismMode
    control_level: ControlLevel
    created_at: datetime
    completed_at: datetime | None
    final_summary: dict[str, Any] | None


class ReplayTaskRequest(BaseModel):
    snapshot_label: str | None = None
    resume_from_snapshot: bool = False
    auto_approve_human_review: bool | None = None


class GraphPatchRequest(BaseModel):
    patch_type: str
    target_node_id: str | None = None
    change_reason: str
    requested_by: str
    approved_by: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    auto_rerun: bool = True


class PlanChangeRequest(BaseModel):
    request_text: str
    requested_by: str = "dashboard-user"
    selected_node_id: str | None = None


class PlanChangeResponse(BaseModel):
    task_id: str
    status: str
    intent: ChangeIntent | None = None
    proposal: PatchProposal | None = None
    validation: PatchValidationResult | None = None
    target_node_resolution: NodeResolutionResult | None = None
    clarification_question: str | None = None


class ApplyPlannedChangeRequest(BaseModel):
    proposal_id: str
    approved_by: str | None = None
    approval_notes: str = ""
    auto_rerun: bool = True


class RunDiffRequest(BaseModel):
    left_task_id: str
    right_task_id: str


class ChangedNodeResponse(BaseModel):
    node_id: str
    changed_fields: list[str] = Field(default_factory=list)
    left_status: str | None = None
    right_status: str | None = None
    left_prompt_hash: str | None = None
    right_prompt_hash: str | None = None
    left_output: dict[str, Any] | None = None
    right_output: dict[str, Any] | None = None


class ChangedPromptResponse(BaseModel):
    phase: str
    node_id: str | None = None
    left_prompt_hash: str
    right_prompt_hash: str


class ChangedEvidenceResponse(BaseModel):
    node_id: str
    left_evidence_ids: list[str] = Field(default_factory=list)
    right_evidence_ids: list[str] = Field(default_factory=list)


class RunDiffResponse(BaseModel):
    left_task_id: str
    right_task_id: str
    changed_nodes: list[ChangedNodeResponse] = Field(default_factory=list)
    changed_prompts: list[ChangedPromptResponse] = Field(default_factory=list)
    changed_evidence: list[ChangedEvidenceResponse] = Field(default_factory=list)
    changed_model_metadata: dict[str, Any] = Field(default_factory=dict)
    changed_final_output: dict[str, Any] = Field(default_factory=dict)


class ReasoningTraceResponse(BaseModel):
    task_id: str
    tier: ReasoningVisibilityTier
    entries: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
