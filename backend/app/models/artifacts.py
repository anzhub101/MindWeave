from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BudgetSpec(BaseModel):
    max_nodes: int
    max_tokens: int
    max_runtime_seconds: int


class AgentToolSpec(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class AgentModelSpec(BaseModel):
    model_id: str | None = None
    model_version: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class AgentSpec(BaseModel):
    persona: str = ""
    instruction: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    tools: list[AgentToolSpec] = Field(default_factory=list)
    model: AgentModelSpec | None = None


class NodeSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    subtitle: str
    operation_type: str
    instruction: str = ""
    success_criteria: list[str] = Field(default_factory=list)
    evaluation_ids: list[str] = Field(default_factory=list)
    input_schema_id: str | None = None
    output_schema_id: str | None = None
    priority: int = 100
    executor_type: str = "llm_operator"
    executor_profile: str | None = None
    agent_spec: AgentSpec | None = None
    max_child_agents: int = 0
    max_recursion_depth: int = 0
    child_token_budget: int = 0
    delegated_summary_required: bool = False
    expansion_contracts: list[str] = Field(default_factory=list)
    required_approvals: int = 0
    depends_on: list[str] = Field(default_factory=list)
    next_nodes: list[str] = Field(default_factory=list, alias="next")
    guarded_by: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReasoningProgram(BaseModel):
    program_id: str
    version: str
    template_id: str
    domain: str = "general"
    goal: str = ""
    policy: str
    budget: BudgetSpec
    convergence_rule: str
    output_schema: str
    deterministic_defaults: dict[str, Any] = Field(default_factory=dict)
    nodes: list[NodeSpec]
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyDefinition(BaseModel):
    policy_id: str
    description: str
    selection_strategy: str
    expansion_rules: list[str] = Field(default_factory=list)
    exploration_limits: dict[str, Any] = Field(default_factory=dict)


class TemplateDefinition(BaseModel):
    template_id: str
    name: str
    description: str
    program_id: str
    program_version: str
    keywords: list[str] = Field(default_factory=list)


class EvaluationDefinition(BaseModel):
    evaluation_id: str
    description: str
    evaluator_type: str
    target_operation_types: list[str] = Field(default_factory=list)
    success_rule: str = ""
    schema_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RegistryArtifact(BaseModel):
    kind: str
    artifact_id: str
    version: str
    name: str
    description: str = ""
    payload: dict[str, Any]
    status: str = "active"
    source: str = "user"
    justification: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ArtifactPromotion(BaseModel):
    kind: str
    artifact_id: str
    version: str
    justification: str
    promoted_at: datetime = Field(default_factory=utcnow)


class SynthesizedProgramBundle(BaseModel):
    template_id: str
    template_name: str
    domain: str
    program: ReasoningProgram
    output_schema_definition: dict[str, Any]
    node_schema_definitions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    mapping_explanation: str = ""
    source_requirements_path: str
