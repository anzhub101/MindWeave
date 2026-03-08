from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NodeResolutionResult(BaseModel):
    status: str = "unresolved"
    query: str = ""
    target_node_id: str | None = None
    candidates: list[str] = Field(default_factory=list)
    matched_aliases: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    question: str | None = None


class ChangeIntent(BaseModel):
    intent_id: str
    task_id: str
    requested_by: str
    requested_at: datetime = Field(default_factory=utcnow)
    intent_type: str
    target_node_id: str | None = None
    target_scope: str = "node_local"
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    confidence: float = 0.0
    source_text: str
    status: str = "proposed"
    resolution: NodeResolutionResult | None = None


class PlannedPatchOperation(BaseModel):
    patch_type: str
    target_node_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    change_reason: str = ""


class PatchProposal(BaseModel):
    proposal_id: str
    intent_id: str
    patches: list[PlannedPatchOperation] = Field(default_factory=list)
    summary: str
    explanation: str = ""
    affected_node_ids: list[str] = Field(default_factory=list)
    rerun_scope: str = "none"
    risk_level: str = "low"
    requires_approval: bool = False
    planner_confidence: float = 0.0
    status: str = "proposed"
    approved_by: str | None = None
    approved_at: datetime | None = None
    applied_at: datetime | None = None
    applied_patch_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class PatchValidationResult(BaseModel):
    proposal_id: str
    status: str = "valid"
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checked_rules: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    affected_nodes: list[str] = Field(default_factory=list)
    validated_at: datetime = Field(default_factory=utcnow)
