from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from jsonschema import validate
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import TaskRunRecord
from app.change_planning.intent_models import PatchProposal
from app.change_planning.intent_parser import IntentParserService
from app.change_planning.patch_planner import PatchPlannerService
from app.change_planning.validation_bridge import ValidationBridge
from app.models.api import (
    ChangedEvidenceResponse,
    ChangedNodeResponse,
    ChangedPromptResponse,
    NodeDetailResponse,
    PlanChangeResponse,
    ReasoningTraceResponse,
    RunDiffResponse,
    TaskRunListItem,
    TaskRunResponse,
    TemplateSummary,
)
from app.models.runtime import (
    ApprovalState,
    ClaimClassification,
    ControlLevel,
    DelegationPolicy,
    DeterminismMode,
    EvidenceSupportLevel,
    ExecutionLogEntry,
    FindingRecord,
    GraphEdge,
    GraphNodeState,
    GraphPatchRecord,
    GraphReasoningState,
    GraphVersionRecord,
    NodeStatus,
    PatchDiffRecord,
    ReasoningVisibilityTier,
    ReviewDecision,
    TaskStatus,
    TraceAccessRecord,
    TraceAccessRole,
    VerificationStatus,
)
from app.runtime.audit import AuditStore
from app.runtime.budget import BudgetManager
from app.runtime.constraints import ConstraintInjector
from app.runtime.controller import Controller
from app.runtime.scheduler import Scheduler
from app.services.artifact_registry_service import ArtifactRegistryService
from app.services.convergence import ConvergenceService
from app.services.document_processor import DocumentProcessor
from app.services.evaluation_service import EvaluationService
from app.services.generic_reasoning_operator import GenericReasoningOperator
from app.services.graph_patch_service import GraphPatchService
from app.services.knowledge_base import KnowledgeBase
from app.services.llm_gateway import LLMGateway
from app.services.node_cache import NodeCacheService
from app.services.program_synthesizer import ProgramSynthesisService
from app.services.review_service import ReviewService
from app.services.runtime_metadata import (
    build_execution_env_hash,
    grs_hash as compute_grs_hash,
    prompt_hash as compute_prompt_hash,
    reproducibility_hash as compute_reproducibility_hash,
    stable_hash,
    ui_model_metadata,
)
from app.services.schema_service import SchemaService
from app.services.storage_service import StorageService
from app.services.tool_runtime import ToolRuntime
from app.services.vector_store import VectorStore


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.storage_service = StorageService(settings=self.settings, storage_root=self.settings.storage_root)
        self.document_processor = DocumentProcessor(storage_service=self.storage_service)
        self.llm_gateway = LLMGateway()
        self.audit_store = AuditStore(self.settings.storage_root, storage_service=self.storage_service)
        self.program_synthesizer = ProgramSynthesisService(self.llm_gateway)
        self.artifact_registry = ArtifactRegistryService(db)
        self.review_service = ReviewService(db)
        self.cache_service = NodeCacheService(db)
        self.vector_store = VectorStore(db)
        self.schema_service = SchemaService(registry=self.artifact_registry)
        self.evaluation_service = EvaluationService(registry=self.artifact_registry, llm_gateway=self.llm_gateway)
        self.tool_runtime = ToolRuntime()
        self.graph_patch_service = GraphPatchService()
        self.intent_parser = IntentParserService()
        self.patch_planner = PatchPlannerService()
        self.validation_bridge = ValidationBridge()

    async def execute_task(
        self,
        prompt: str,
        deterministic: bool,
        auto_approve_human_review: bool,
        use_sample_data: bool,
        files: list,
        execution_overrides: dict[str, Any] | None = None,
        determinism_mode: DeterminismMode | None = None,
        control_level: ControlLevel = ControlLevel.operational,
    ) -> TaskRunResponse:
        determinism_mode, auto_approve_human_review, visibility_tier = self._resolve_execution_controls(
            deterministic=deterministic,
            determinism_mode=determinism_mode,
            control_level=control_level,
            auto_approve_human_review=auto_approve_human_review,
        )
        synthesized = self.program_synthesizer.synthesize(
            prompt,
            deterministic=determinism_mode == DeterminismMode.strict_deterministic,
            determinism_mode=determinism_mode.value,
        )
        synthesized = self._apply_execution_overrides(synthesized, execution_overrides)
        self.artifact_registry.register_bundle(synthesized)
        self.schema_service.register_bundle_schemas(synthesized)
        task_id = uuid4().hex[:12]

        if files:
            documents = await self.document_processor.store_uploads(task_id, files)
        elif use_sample_data:
            documents = self.document_processor.load_sample_pack(task_id)
        else:
            documents = []

        provider_metadata = self.program_synthesizer.last_provider_metadata or self.llm_gateway.describe_provider(determinism_mode.value)

        graph_started = perf_counter()
        state = self._instantiate_state(
            task_id=task_id,
            prompt=prompt,
            bundle=synthesized,
            documents=documents,
            determinism_mode=determinism_mode,
            control_level=control_level,
            visibility_tier=visibility_tier,
            provider_metadata=provider_metadata,
        )
        state.graph_build_ms = int((perf_counter() - graph_started) * 1000)
        self._apply_control_requirements(state, auto_approve_human_review=auto_approve_human_review)
        if self.program_synthesizer.last_prompt_trace is not None:
            state.prompt_traces.append(self.program_synthesizer.last_prompt_trace)

        state.logs.append(
            ExecutionLogEntry(
                event="program_synthesized",
                message="Prompt-to-plan synthesis completed from the requirements reference.",
                payload={
                    "domain": synthesized.domain,
                    "mapping_explanation": synthesized.mapping_explanation,
                    "template_id": synthesized.template_id,
                    "program_id": synthesized.program.program_id,
                },
            )
        )
        state.logs.append(
            ExecutionLogEntry(
                event="determinism_profile_initialized",
                message="Execution determinism profile initialized.",
                payload={
                    "determinism_mode": state.determinism_mode.value,
                    "control_level": state.control_level.value,
                    "model_id": state.model_id,
                    "model_version": state.model_version,
                    "provider_fingerprint": state.provider_fingerprint,
                    "execution_env_hash": state.execution_env_hash,
                },
            )
        )
        state.logs.append(
            ExecutionLogEntry(
                event="graph_built",
                message="Graph Reasoning State instantiated.",
                payload={"graph_build_ms": state.graph_build_ms or 0},
            )
        )

        controller = self._build_controller(
            task_id=task_id,
            documents=documents,
            auto_approve_human_review=auto_approve_human_review,
        )
        state = controller.run(state)
        self._finalize_state(state, provider_metadata)

        self.audit_store.snapshot(state, "final")
        audit_package, _ = self.audit_store.persist_audit_package(state)
        self._persist_record(state, audit_package)
        return self._build_response(state, audit_package)

    def list_tasks(self) -> list[TaskRunListItem]:
        records = self.db.query(TaskRunRecord).order_by(TaskRunRecord.created_at.desc()).limit(20).all()
        items: list[TaskRunListItem] = []
        for record in records:
            state = GraphReasoningState.model_validate(record.grs_snapshot)
            items.append(
                TaskRunListItem(
                    task_id=record.task_id,
                    prompt=record.prompt,
                    status=TaskStatus(record.status),
                    template_id=record.template_id,
                    program_id=record.program_id,
                    domain=record.domain,
                    determinism_mode=state.determinism_mode,
                    control_level=state.control_level,
                    created_at=record.created_at,
                    completed_at=record.updated_at,
                    final_summary=record.audit_package.get("final_summary"),
                )
            )
        return items

    def get_task(self, task_id: str) -> TaskRunResponse:
        record = self._require_record(task_id)
        state = GraphReasoningState.model_validate(record.grs_snapshot)
        state.review_history = self.review_service.list_for_task(task_id)
        if not state.graph_version_history:
            self._ensure_initial_graph_version(state)
            audit_package, _ = self.audit_store.persist_audit_package(state)
            self._persist_record(state, audit_package)
            record.audit_package = audit_package
        return self._build_response(state, record.audit_package)

    def get_audit_package(self, task_id: str) -> dict:
        record = self._require_record(task_id)
        state = GraphReasoningState.model_validate(record.grs_snapshot)
        if not state.graph_version_history:
            self._ensure_initial_graph_version(state)
            audit_package, _ = self.audit_store.persist_audit_package(state)
            self._persist_record(state, audit_package)
            return audit_package
        return record.audit_package

    def get_node_detail(self, task_id: str, node_id: str) -> NodeDetailResponse:
        state = GraphReasoningState.model_validate(self._require_record(task_id).grs_snapshot)
        node = state.nodes.get(node_id)
        if node is None:
            raise ValueError(f"Node {node_id} not found for task {task_id}.")
        return self._build_node_detail(state, node)

    def list_reviews(self, task_id: str) -> list[ReviewDecision]:
        return self.review_service.list_for_task(task_id)

    def submit_review(self, task_id: str, decision: ReviewDecision) -> TaskRunResponse:
        record = self._require_record(task_id)
        state = GraphReasoningState.model_validate(record.grs_snapshot)
        saved_decision = self.review_service.record(task_id, decision)
        state.review_history.append(saved_decision)

        node_id = state.pending_review_node_id or decision.node_id
        node = state.nodes.get(node_id) if node_id else None
        if node is None:
            raise ValueError("Pending review node not found.")

        if decision.decision.lower() in {"approved", "approve"}:
            required_approvals = max(node.required_approvals, 1 if node.metadata.get("requires_human_review") else 0)
            approved_count = self._approved_count(state, node.id)
            if approved_count >= required_approvals:
                node.metadata["review_approved"] = True
                state.pending_review_node_id = None
                state.status = TaskStatus.running
                controller = self._build_controller(
                    task_id=task_id,
                    documents=state.source_documents,
                    auto_approve_human_review=False,
                )
                state = controller.run(state)
            else:
                state.status = TaskStatus.paused
                state.pending_review_node_id = node.id
                state.logs.append(
                    ExecutionLogEntry(
                        event="human_review_partial_approval",
                        message=f"Recorded approval {approved_count}/{required_approvals} for node {node.id}.",
                        node_id=node.id,
                    )
                )
        else:
            state.status = TaskStatus.failed
            state.logs.append(
                ExecutionLogEntry(
                    event="human_review_rejected",
                    message=decision.comments or "Human reviewer rejected the pending node.",
                    node_id=decision.node_id,
                )
            )
            state.pending_review_node_id = None

        provider_metadata = self.llm_gateway.describe_provider(state.determinism_mode.value)
        self._finalize_state(state, provider_metadata)
        self.audit_store.snapshot(state, "final")
        audit_package, _ = self.audit_store.persist_audit_package(state)
        self._persist_record(state, audit_package)
        return self._build_response(state, audit_package)

    def replay_task(
        self,
        task_id: str,
        snapshot_label: str | None = None,
        resume_from_snapshot: bool = False,
        auto_approve_human_review: bool | None = None,
    ) -> TaskRunResponse:
        if snapshot_label is not None:
            state, resolved_label = self.audit_store.load_snapshot(task_id, snapshot_label)
        else:
            record = self._require_record(task_id)
            state = GraphReasoningState.model_validate(record.grs_snapshot)
            resolved_label = "record_snapshot"

        original_reproducibility_hash = state.reproducibility_hash
        original_grs_hash = state.grs_hash
        original_prompt_hash = state.prompt_hash
        original_task_id = state.task_id
        state.task_id = uuid4().hex[:12]
        state.replay_of_task_id = original_task_id
        state.replay_source_snapshot_label = resolved_label
        if not resume_from_snapshot:
            state = self._reset_state_for_replay(state)

        auto_approve = auto_approve_human_review if auto_approve_human_review is not None else False
        controller = self._build_controller(
            task_id=state.task_id,
            documents=state.source_documents,
            auto_approve_human_review=auto_approve,
        )
        provider_metadata = self.llm_gateway.describe_provider(state.determinism_mode.value)
        state = controller.run(state)
        self._finalize_state(state, provider_metadata)
        if state.reproducibility_hash != original_reproducibility_hash:
            state.logs.append(
                ExecutionLogEntry(
                    event="determinism_variance_detected",
                    message="Replay run produced a different reproducibility hash than the source run.",
                    payload={
                        "source_task_id": original_task_id,
                        "source_snapshot_label": resolved_label,
                        "original_prompt_hash": original_prompt_hash,
                        "new_prompt_hash": state.prompt_hash,
                        "original_grs_hash": original_grs_hash,
                        "new_grs_hash": state.grs_hash,
                        "original_reproducibility_hash": original_reproducibility_hash,
                        "new_reproducibility_hash": state.reproducibility_hash,
                    },
                )
            )
        else:
            state.logs.append(
                ExecutionLogEntry(
                    event="determinism_replay_matched",
                    message="Replay run matched the source reproducibility hash.",
                    payload={
                        "source_task_id": original_task_id,
                        "source_snapshot_label": resolved_label,
                        "reproducibility_hash": state.reproducibility_hash,
                    },
                )
            )
        self.audit_store.snapshot(state, "final")
        audit_package, _ = self.audit_store.persist_audit_package(state)
        self._persist_record(state, audit_package)
        return self._build_response(state, audit_package)

    def apply_graph_patch(
        self,
        task_id: str,
        patch_type: str,
        target_node_id: str | None,
        change_reason: str,
        requested_by: str,
        approved_by: str | None,
        payload: dict[str, Any] | None,
        auto_rerun: bool,
    ) -> TaskRunResponse:
        record = self._require_record(task_id)
        state = GraphReasoningState.model_validate(record.grs_snapshot)
        self._ensure_initial_graph_version(state)
        validation = self.validation_bridge.validate_patch(
            state=state,
            patch_type=patch_type,
            target_node_id=target_node_id,
            payload=payload or {},
            change_reason=change_reason,
        )
        if validation.status != "valid":
            raise ValueError("; ".join(validation.errors) or "Patch validation failed.")
        if validation.requires_approval and not approved_by:
            raise ValueError("This patch requires approval before it can be applied.")
        if validation.warnings:
            state.logs.append(
                ExecutionLogEntry(
                    event="graph_patch_validated_with_warnings",
                    message="Graph patch validation completed with warnings.",
                    node_id=target_node_id,
                    payload=validation.model_dump(mode="json"),
                )
            )
        before_state = GraphReasoningState.model_validate(state.model_dump(mode="json"))
        patch = self.graph_patch_service.apply(
            state=state,
            patch_type=patch_type,
            target_node_id=target_node_id,
            change_reason=change_reason,
            requested_by=requested_by,
            approved_by=approved_by,
            payload=payload,
            auto_rerun=auto_rerun,
        )
        state.logs.append(
            ExecutionLogEntry(
                event="graph_patch_applied",
                message=f"Applied graph patch {patch.patch_type}.",
                node_id=target_node_id,
                payload=patch.model_dump(mode="json"),
            )
        )
        self._record_patch_governance(state, before_state, patch, requested_by, change_reason)

        if auto_rerun:
            if patch.patch_type == "remove_node":
                state = self._reset_state_for_replay(state)
            elif target_node_id and target_node_id in state.nodes:
                self.graph_patch_service._reset_subtree(state, target_node_id)
            controller = self._build_controller(
                task_id=task_id,
                documents=state.source_documents,
                auto_approve_human_review=False,
            )
            state = controller.run(state)

        provider_metadata = self.llm_gateway.describe_provider(state.determinism_mode.value)
        self._finalize_state(state, provider_metadata)
        self.audit_store.snapshot(state, "final")
        audit_package, _ = self.audit_store.persist_audit_package(state)
        self._persist_record(state, audit_package)
        return self._build_response(state, audit_package)

    def change_node_executor(
        self,
        task_id: str,
        node_id: str,
        executor_type: str,
        executor_profile: str | None,
        max_child_agents: int,
        max_recursion_depth: int,
        child_token_budget: int,
        delegated_summary_required: bool,
        requested_by: str,
        approved_by: str | None,
        change_reason: str,
        instruction_note: str,
        auto_rerun: bool,
    ) -> TaskRunResponse:
        payload: dict[str, Any] = {
            "executor_type": executor_type,
            "max_child_agents": max_child_agents,
            "max_recursion_depth": max_recursion_depth,
            "child_token_budget": child_token_budget,
            "delegated_summary_required": delegated_summary_required,
        }
        if executor_profile:
            payload["executor_profile"] = executor_profile
        if instruction_note.strip():
            payload["instruction_note"] = instruction_note.strip()
        return self.apply_graph_patch(
            task_id=task_id,
            patch_type="change_executor",
            target_node_id=node_id,
            change_reason=change_reason or f"Change executor for node {node_id}.",
            requested_by=requested_by,
            approved_by=approved_by or requested_by,
            payload=payload,
            auto_rerun=auto_rerun,
        )

    def plan_change(
        self,
        task_id: str,
        request_text: str,
        requested_by: str,
        selected_node_id: str | None = None,
    ) -> PlanChangeResponse:
        record = self._require_record(task_id)
        state = GraphReasoningState.model_validate(record.grs_snapshot)
        intent = self.intent_parser.parse(
            task_id=task_id,
            state=state,
            request_text=request_text,
            requested_by=requested_by,
            selected_node_id=selected_node_id,
        )
        state.change_intents.append(intent)
        state.logs.append(
            ExecutionLogEntry(
                event="nl_change_requested",
                message="Received natural language graph change request.",
                node_id=intent.target_node_id,
                payload={
                    "source_text": request_text,
                    "requested_by": requested_by,
                    "intent_id": intent.intent_id,
                    "intent_type": intent.intent_type,
                    "confidence": intent.confidence,
                    "target_node_resolution": intent.resolution.model_dump(mode="json") if intent.resolution else None,
                },
            )
        )

        if intent.status == "needs_clarification":
            state.logs.append(
                ExecutionLogEntry(
                    event="nl_change_clarification_required",
                    message="Natural language change request needs clarification before a patch can be proposed.",
                    node_id=intent.target_node_id,
                    payload={"intent_id": intent.intent_id},
                )
            )
            self._snapshot_and_persist_state(state, label="planned_change")
            clarification_question = intent.resolution.question if intent.resolution else "Please clarify the node or change scope."
            return PlanChangeResponse(
                task_id=task_id,
                status="needs_clarification",
                intent=intent,
                target_node_resolution=intent.resolution,
                clarification_question=clarification_question,
            )

        proposal = self.patch_planner.build(state, intent)
        validation = self.validation_bridge.validate(state, proposal)
        if validation.status == "invalid":
            proposal.status = "invalid"
            intent.status = "invalid"

        state.patch_proposals.append(proposal)
        state.patch_validation_history.append(validation)
        state.logs.append(
            ExecutionLogEntry(
                event="nl_patch_proposed",
                message="Generated a structured patch proposal from the natural language request.",
                node_id=intent.target_node_id,
                payload={
                    "intent_id": intent.intent_id,
                    "proposal_id": proposal.proposal_id,
                    "planner_confidence": proposal.planner_confidence,
                    "risk_level": proposal.risk_level,
                    "requires_approval": proposal.requires_approval,
                    "validation_status": validation.status,
                },
            )
        )
        self._snapshot_and_persist_state(state, label="planned_change")
        return PlanChangeResponse(
            task_id=task_id,
            status="proposed" if validation.status == "valid" else "invalid",
            intent=intent,
            proposal=proposal,
            validation=validation,
            target_node_resolution=intent.resolution,
        )

    def plan_node_change(
        self,
        task_id: str,
        node_id: str,
        request_text: str,
        requested_by: str,
    ) -> PlanChangeResponse:
        return self.plan_change(
            task_id=task_id,
            request_text=request_text,
            requested_by=requested_by,
            selected_node_id=node_id,
        )

    def apply_planned_change(
        self,
        task_id: str,
        proposal_id: str,
        approved_by: str | None,
        approval_notes: str = "",
        auto_rerun: bool = True,
    ) -> TaskRunResponse:
        record = self._require_record(task_id)
        state = GraphReasoningState.model_validate(record.grs_snapshot)
        self._ensure_initial_graph_version(state)
        proposal = next((item for item in state.patch_proposals if item.proposal_id == proposal_id), None)
        if proposal is None:
            raise ValueError(f"Patch proposal {proposal_id} not found.")
        validation = next((item for item in reversed(state.patch_validation_history) if item.proposal_id == proposal_id), None)
        if validation is None:
            raise ValueError(f"No validation record found for proposal {proposal_id}.")
        if validation.status != "valid":
            raise ValueError("Only validated proposals can be applied.")
        if self._proposal_requires_approval(state, proposal) and not approved_by:
            raise ValueError("This proposal requires approval before it can be applied.")

        intent = next((item for item in state.change_intents if item.intent_id == proposal.intent_id), None)
        applied_patch_ids: list[str] = []
        for patch in proposal.patches:
            before_state = GraphReasoningState.model_validate(state.model_dump(mode="json"))
            applied = self.graph_patch_service.apply(
                state=state,
                patch_type=patch.patch_type,
                target_node_id=patch.target_node_id,
                change_reason=patch.change_reason or proposal.summary,
                requested_by=intent.requested_by if intent is not None else "planner",
                approved_by=approved_by,
                payload=patch.payload,
                auto_rerun=auto_rerun,
            )
            applied_patch_ids.append(applied.patch_id)
            self._record_patch_governance(
                state,
                before_state,
                applied,
                intent.requested_by if intent is not None else "planner",
                patch.change_reason or proposal.summary,
            )

        proposal.status = "applied"
        proposal.approved_by = approved_by
        proposal.approved_at = utcnow() if approved_by else None
        proposal.applied_at = utcnow()
        proposal.applied_patch_ids = applied_patch_ids
        if intent is not None:
            intent.status = "applied"

        state.logs.append(
            ExecutionLogEntry(
                event="nl_patch_applied",
                message="Applied a validated patch proposal.",
                payload={
                    "proposal_id": proposal.proposal_id,
                    "intent_id": proposal.intent_id,
                    "approved_by": approved_by,
                    "approval_notes": approval_notes,
                    "applied_patch_ids": applied_patch_ids,
                },
            )
        )

        if auto_rerun:
            controller = self._build_controller(
                task_id=task_id,
                documents=state.source_documents,
                auto_approve_human_review=False,
            )
            state = controller.run(state)

        provider_metadata = self.llm_gateway.describe_provider(state.determinism_mode.value)
        self._finalize_state(state, provider_metadata)
        self.audit_store.snapshot(state, "final")
        audit_package, _ = self.audit_store.persist_audit_package(state)
        self._persist_record(state, audit_package)
        return self._build_response(state, audit_package)

    def diff_runs(self, left_task_id: str, right_task_id: str) -> RunDiffResponse:
        left = GraphReasoningState.model_validate(self._require_record(left_task_id).grs_snapshot)
        right = GraphReasoningState.model_validate(self._require_record(right_task_id).grs_snapshot)

        changed_nodes: list[ChangedNodeResponse] = []
        all_node_ids = sorted(set(left.nodes.keys()) | set(right.nodes.keys()))
        for node_id in all_node_ids:
            left_node = left.nodes.get(node_id)
            right_node = right.nodes.get(node_id)
            changed_fields: list[str] = []
            if left_node is None or right_node is None:
                changed_fields.append("presence")
            else:
                if left_node.status != right_node.status:
                    changed_fields.append("status")
                if left_node.prompt_hash != right_node.prompt_hash:
                    changed_fields.append("prompt_hash")
                if stable_hash(left_node.output) != stable_hash(right_node.output):
                    changed_fields.append("output")
                if stable_hash([reference.chunk_id for reference in left_node.evidence_refs]) != stable_hash(
                    [reference.chunk_id for reference in right_node.evidence_refs]
                ):
                    changed_fields.append("evidence")
                if stable_hash(left_node.model_metadata) != stable_hash(right_node.model_metadata):
                    changed_fields.append("model_metadata")
            if changed_fields:
                changed_nodes.append(
                    ChangedNodeResponse(
                        node_id=node_id,
                        changed_fields=changed_fields,
                        left_status=left_node.status.value if left_node is not None else None,
                        right_status=right_node.status.value if right_node is not None else None,
                        left_prompt_hash=left_node.prompt_hash if left_node is not None else None,
                        right_prompt_hash=right_node.prompt_hash if right_node is not None else None,
                        left_output=left_node.output if left_node is not None else None,
                        right_output=right_node.output if right_node is not None else None,
                    )
                )

        changed_prompts: list[ChangedPromptResponse] = []
        left_traces = {(trace.phase, trace.node_id): trace for trace in left.prompt_traces}
        right_traces = {(trace.phase, trace.node_id): trace for trace in right.prompt_traces}
        for key in sorted(set(left_traces.keys()) | set(right_traces.keys())):
            left_trace = left_traces.get(key)
            right_trace = right_traces.get(key)
            left_hash = left_trace.prompt_hash if left_trace is not None else ""
            right_hash = right_trace.prompt_hash if right_trace is not None else ""
            if left_hash != right_hash:
                changed_prompts.append(
                    ChangedPromptResponse(
                        phase=key[0],
                        node_id=key[1],
                        left_prompt_hash=left_hash,
                        right_prompt_hash=right_hash,
                    )
                )

        changed_evidence: list[ChangedEvidenceResponse] = []
        for node_id in all_node_ids:
            left_refs = left.nodes.get(node_id).evidence_refs if node_id in left.nodes else []
            right_refs = right.nodes.get(node_id).evidence_refs if node_id in right.nodes else []
            left_ids = [reference.chunk_id for reference in left_refs]
            right_ids = [reference.chunk_id for reference in right_refs]
            if left_ids != right_ids:
                changed_evidence.append(
                    ChangedEvidenceResponse(
                        node_id=node_id,
                        left_evidence_ids=left_ids,
                        right_evidence_ids=right_ids,
                    )
                )

        return RunDiffResponse(
            left_task_id=left_task_id,
            right_task_id=right_task_id,
            changed_nodes=changed_nodes,
            changed_prompts=changed_prompts,
            changed_evidence=changed_evidence,
            changed_model_metadata={
                "left": {
                    "determinism_mode": left.determinism_mode.value,
                    "model_id": left.model_id,
                    "model_version": left.model_version,
                    "provider_fingerprint": left.provider_fingerprint,
                    "execution_env_hash": left.execution_env_hash,
                },
                "right": {
                    "determinism_mode": right.determinism_mode.value,
                    "model_id": right.model_id,
                    "model_version": right.model_version,
                    "provider_fingerprint": right.provider_fingerprint,
                    "execution_env_hash": right.execution_env_hash,
                },
            },
            changed_final_output={
                "left": left.final_output,
                "right": right.final_output,
                "changed": stable_hash(left.final_output or {}) != stable_hash(right.final_output or {}),
            },
        )

    def get_reasoning_trace(
        self,
        task_id: str,
        tier: ReasoningVisibilityTier,
        viewer_role: TraceAccessRole = TraceAccessRole.reviewer,
        viewer_id: str = "anonymous",
    ) -> ReasoningTraceResponse:
        state = GraphReasoningState.model_validate(self._require_record(task_id).grs_snapshot)
        self._ensure_initial_graph_version(state)
        effective_tier = self._cap_visibility_tier_for_role(state.control_level, viewer_role, tier)
        entries: list[dict[str, Any]] = []

        ordered_nodes = sorted(
            state.nodes.values(),
            key=lambda node: (
                node.metadata.get("layout", {}).get("row", 999),
                node.metadata.get("layout", {}).get("column", 999),
                node.priority,
            ),
        )
        for node in ordered_nodes:
            base_entry = {
                "node_id": node.id,
                "title": node.title,
                "status": node.status.value,
                "evidence_used": [reference.model_dump(mode="json") for reference in node.evidence_refs],
                "conclusion": node.output.get("conclusion") or node.output.get("summary") or node.subtitle,
                "claims": self._serialize_claims(node),
            }
            if effective_tier == ReasoningVisibilityTier.summary_trace:
                entries.append(base_entry)
                continue

            structured_entry = {
                **base_entry,
                "inputs": node.inputs,
                "output": node.output,
                "verification_status": node.verification_status.value,
                "score": node.evaluation_score,
                "prompt_hash": node.prompt_hash,
            }
            if effective_tier == ReasoningVisibilityTier.structured_reasoning_trace:
                entries.append(structured_entry)
                continue

            entries.append(
                {
                    **structured_entry,
                    "thought_summary": state.thoughts.get(f"thought_{node.id}").summary if f"thought_{node.id}" in state.thoughts else "",
                    "expansion_contracts": node.expansion_contracts,
                    "delegated_from": node.spawned_from,
                    "model_metadata": node.model_metadata,
                }
            )

        state.trace_access_history.append(
            TraceAccessRecord(
                task_id=task_id,
                viewer_id=viewer_id,
                viewer_role=viewer_role,
                requested_tier=tier,
                effective_tier=effective_tier,
                entry_count=len(entries),
            )
        )
        state.logs.append(
            ExecutionLogEntry(
                event="reasoning_trace_viewed",
                message="Reasoning trace was accessed.",
                payload={
                    "viewer_id": viewer_id,
                    "viewer_role": viewer_role.value,
                    "requested_tier": tier.value,
                    "effective_tier": effective_tier.value,
                    "entry_count": len(entries),
                },
            )
        )
        audit_package, _ = self.audit_store.persist_audit_package(state)
        self._persist_record(state, audit_package)

        return ReasoningTraceResponse(
            task_id=task_id,
            tier=effective_tier,
            entries=entries,
            metadata={
                "control_level": state.control_level.value,
                "requested_tier": tier.value,
                "effective_tier": effective_tier.value,
                "viewer_role": viewer_role.value,
                "viewer_id": viewer_id,
                "access_count": len(state.trace_access_history),
                "execution_sequence": state.execution_sequence,
            },
        )

    def list_templates(self) -> list[TemplateSummary]:
        templates = [
            TemplateSummary(
                template_id=artifact.artifact_id,
                name=artifact.name,
                description=artifact.description,
            )
            for artifact in self.artifact_registry.list("template")
        ]
        templates.insert(
            0,
            TemplateSummary(
                template_id="generated_from_requirements",
                name="Generated From Requirements",
                description="Synthesizes a reasoning program from the requirements reference and the user prompt.",
            ),
        )
        return templates

    def _instantiate_state(
        self,
        task_id: str,
        prompt: str,
        bundle,
        documents,
        determinism_mode: DeterminismMode,
        control_level: ControlLevel,
        visibility_tier: ReasoningVisibilityTier,
        provider_metadata: dict[str, Any],
    ) -> GraphReasoningState:
        program = bundle.program
        nodes = {
            node.id: GraphNodeState(
                id=node.id,
                title=node.title,
                subtitle=node.subtitle,
                operation_type=node.operation_type,
                instruction=node.instruction,
                success_criteria=node.success_criteria,
                evaluation_ids=node.evaluation_ids,
                input_schema_id=node.input_schema_id,
                output_schema_id=node.output_schema_id,
                priority=node.priority,
                executor_type=node.executor_type,
                executor_profile=getattr(node, "executor_profile", None) or node.metadata.get("executor_profile"),
                max_child_agents=node.max_child_agents,
                max_recursion_depth=node.max_recursion_depth,
                child_token_budget=int(getattr(node, "child_token_budget", 0) or node.metadata.get("child_token_budget", 0) or 0),
                expansion_contracts=node.expansion_contracts,
                delegated_summary_required=bool(
                    getattr(node, "delegated_summary_required", False) or node.metadata.get("delegated_summary_required", False)
                ),
                required_approvals=node.required_approvals,
                depends_on=node.depends_on,
                guarded_by=node.guarded_by,
                next_nodes=node.next_nodes,
                metadata=node.metadata,
            )
            for node in program.nodes
        }
        edges = [
            GraphEdge(source=node.id, target=target_id)
            for node in program.nodes
            for target_id in node.next_nodes
        ]
        prompt_hash = compute_prompt_hash(
            prompt=prompt,
            params={"determinism_mode": determinism_mode.value, "control_level": control_level.value},
        )
        state = GraphReasoningState(
            task_id=task_id,
            prompt=prompt,
            template_id=bundle.template_id,
            program_id=program.program_id,
            program_version=program.version,
            domain=program.domain,
            deterministic=determinism_mode != DeterminismMode.non_deterministic,
            determinism_mode=determinism_mode,
            control_level=control_level,
            default_visibility_tier=visibility_tier,
            model_id=str(provider_metadata.get("model_id") or ""),
            model_version=str(provider_metadata.get("model_version") or provider_metadata.get("model_id") or ""),
            provider_fingerprint=str(provider_metadata.get("provider_fingerprint") or ""),
            execution_endpoint=provider_metadata.get("endpoint"),
            prompt_hash=prompt_hash,
            requirements_reference_path=bundle.source_requirements_path,
            source_documents=documents,
            nodes=nodes,
            edges=edges,
            budget_spec=program.budget,
            delegation_policy=DelegationPolicy.model_validate(
                (program.metadata or {}).get("delegation_policy", {})
                if isinstance(program.metadata, dict)
                else {}
            ),
            program_blueprint=program.model_dump(mode="json", by_alias=True),
            output_schema_definition=bundle.output_schema_definition,
        )
        state.execution_env_hash = build_execution_env_hash(self.settings, determinism_mode.value, provider_metadata)
        state.grs_hash = compute_grs_hash(state)
        state.reproducibility_hash = compute_reproducibility_hash(state, provider_metadata)
        self._ensure_initial_graph_version(state)
        return state

    def _persist_record(self, state: GraphReasoningState, audit_package: dict) -> None:
        existing = self.db.query(TaskRunRecord).filter(TaskRunRecord.task_id == state.task_id).one_or_none()
        payload = {
            "task_id": state.task_id,
            "prompt": state.prompt,
            "template_id": state.template_id,
            "program_id": state.program_id,
            "program_version": state.program_version,
            "domain": state.domain,
            "status": state.status.value,
            "deterministic": state.deterministic,
            "source_documents": [document.model_dump(mode="json") for document in state.source_documents],
            "final_output": state.final_output,
            "grs_snapshot": state.model_dump(mode="json"),
            "audit_package": audit_package,
        }
        if existing is None:
            record = TaskRunRecord(**payload)
            self.db.add(record)
        else:
            for key, value in payload.items():
                setattr(existing, key, value)
        self.db.commit()

    def _snapshot_and_persist_state(self, state: GraphReasoningState, label: str) -> None:
        self.audit_store.snapshot(state, label)
        audit_package, _ = self.audit_store.persist_audit_package(state)
        self._persist_record(state, audit_package)

    @staticmethod
    def _edge_key(edge: GraphEdge) -> str:
        return f"{edge.source}->{edge.target}:{edge.kind}"

    def _ensure_initial_graph_version(self, state: GraphReasoningState) -> None:
        if state.graph_version_history:
            return
        state.graph_version_history.append(
            GraphVersionRecord(
                program_version=state.program_version,
                blueprint_hash=stable_hash(state.program_blueprint or {}),
                created_by="system",
                reason="Initial graph instantiation.",
            )
        )

    def _record_patch_governance(
        self,
        state: GraphReasoningState,
        before_state: GraphReasoningState,
        patch: GraphPatchRecord,
        requested_by: str,
        reason: str,
    ) -> None:
        self._ensure_initial_graph_version(state)
        self._ensure_initial_graph_version(before_state)
        state.patch_diff_history.append(self._build_patch_diff(before_state, state, patch))
        state.graph_version_history.append(
            GraphVersionRecord(
                program_version=state.program_version,
                blueprint_hash=stable_hash(state.program_blueprint or {}),
                created_by=requested_by,
                reason=reason,
                patch_id=patch.patch_id,
                parent_program_version=before_state.program_version,
            )
        )

    def _build_patch_diff(
        self,
        before_state: GraphReasoningState,
        after_state: GraphReasoningState,
        patch: GraphPatchRecord,
    ) -> PatchDiffRecord:
        before_node_ids = set(before_state.nodes.keys())
        after_node_ids = set(after_state.nodes.keys())
        common_node_ids = before_node_ids & after_node_ids
        changed_nodes = sorted(
            node_id
            for node_id in common_node_ids
            if stable_hash(before_state.nodes[node_id].model_dump(mode="json"))
            != stable_hash(after_state.nodes[node_id].model_dump(mode="json"))
        )
        before_edges = {self._edge_key(edge) for edge in before_state.edges}
        after_edges = {self._edge_key(edge) for edge in after_state.edges}
        return PatchDiffRecord(
            patch_id=patch.patch_id,
            patch_type=patch.patch_type,
            before_program_version=before_state.program_version,
            after_program_version=after_state.program_version,
            before_blueprint_hash=stable_hash(before_state.program_blueprint or {}),
            after_blueprint_hash=stable_hash(after_state.program_blueprint or {}),
            added_nodes=sorted(after_node_ids - before_node_ids),
            removed_nodes=sorted(before_node_ids - after_node_ids),
            changed_nodes=changed_nodes,
            added_edges=sorted(after_edges - before_edges),
            removed_edges=sorted(before_edges - after_edges),
            changed_policy=(before_state.program_blueprint or {}).get("policy")
            != (after_state.program_blueprint or {}).get("policy"),
            changed_budget=stable_hash(before_state.budget_spec.model_dump(mode="json"))
            != stable_hash(after_state.budget_spec.model_dump(mode="json")),
        )

    @staticmethod
    def _tier_rank(tier: ReasoningVisibilityTier) -> int:
        ranking = {
            ReasoningVisibilityTier.summary_trace: 0,
            ReasoningVisibilityTier.structured_reasoning_trace: 1,
            ReasoningVisibilityTier.expanded_analytic_trace: 2,
        }
        return ranking[tier]

    def _cap_visibility_tier_for_role(
        self,
        control_level: ControlLevel,
        viewer_role: TraceAccessRole,
        requested_tier: ReasoningVisibilityTier,
    ) -> ReasoningVisibilityTier:
        control_cap = self._cap_visibility_tier(control_level, requested_tier)
        role_cap = {
            TraceAccessRole.viewer: ReasoningVisibilityTier.summary_trace,
            TraceAccessRole.reviewer: ReasoningVisibilityTier.structured_reasoning_trace,
            TraceAccessRole.auditor: ReasoningVisibilityTier.expanded_analytic_trace,
            TraceAccessRole.admin: ReasoningVisibilityTier.expanded_analytic_trace,
        }[viewer_role]
        allowed_rank = min(self._tier_rank(control_cap), self._tier_rank(role_cap), self._tier_rank(requested_tier))
        ranked_tiers = {
            0: ReasoningVisibilityTier.summary_trace,
            1: ReasoningVisibilityTier.structured_reasoning_trace,
            2: ReasoningVisibilityTier.expanded_analytic_trace,
        }
        return ranked_tiers[allowed_rank]

    @staticmethod
    def _serialize_claims(node: GraphNodeState) -> list[dict[str, Any]]:
        return [
            {
                "id": record.id,
                "text": record.text,
                "support_level": record.support_level.value,
                "claim_classification": record.claim_classification.value,
                "evidence_refs": [reference.model_dump(mode="json") for reference in record.evidence_refs],
            }
            for record in node.finding_records
        ]

    def _approval_state_for_node(self, state: GraphReasoningState, node: GraphNodeState) -> ApprovalState:
        requires_human_review = bool(node.metadata.get("requires_human_review")) or node.required_approvals > 0
        approved_count = self._approved_count(state, node.id)
        required_approvals = max(node.required_approvals, 1 if requires_human_review else 0)
        pending_approvals = max(required_approvals - approved_count, 0)
        if required_approvals == 0:
            status = "not_required"
        elif pending_approvals == 0:
            status = "approved"
        elif approved_count > 0:
            status = "partially_approved"
        else:
            status = "pending"
        return ApprovalState(
            required_approvals=required_approvals,
            approved_count=approved_count,
            pending_approvals=pending_approvals,
            requires_human_review=requires_human_review,
            status=status,
        )

    @staticmethod
    def _key_conclusion_for_node(node: GraphNodeState) -> str:
        for candidate in (
            node.output.get("conclusion"),
            node.output.get("summary"),
            node.thought_summary,
            node.subtitle,
        ):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return ""

    @staticmethod
    def _patch_history_for_node(state: GraphReasoningState, node_id: str) -> list[GraphPatchRecord]:
        history: list[GraphPatchRecord] = []
        for patch in state.graph_patch_history:
            if patch.target_node_id == node_id:
                history.append(patch)
                continue
            raw_node = patch.payload.get("node", {}) if isinstance(patch.payload, dict) else {}
            if isinstance(raw_node, dict) and str(raw_node.get("id") or "") == node_id:
                history.append(patch)
        return history

    def _prepared_node(self, state: GraphReasoningState, node: GraphNodeState) -> GraphNodeState:
        prepared = GraphNodeState.model_validate(node.model_dump(mode="json"))
        if not prepared.executor_profile:
            prepared.executor_profile = node.metadata.get("executor_profile")
        if not prepared.thought_summary:
            thought = state.thoughts.get(f"thought_{node.id}")
            prepared.thought_summary = thought.summary if thought is not None else node.subtitle
        if not prepared.verification_checks:
            for entry in reversed(state.verification_logs):
                if entry.node_id == node.id:
                    prepared.verification_checks = list(entry.checks)
                    break
        prepared.approval_state = self._approval_state_for_node(state, node)
        if not prepared.delegated_children:
            prepared.delegated_children = list(node.metadata.get("spawned_child_ids", []))
        prepared.patch_history = [patch.patch_id for patch in self._patch_history_for_node(state, node.id)]
        prepared.model_metadata = ui_model_metadata(node.model_metadata)
        return prepared

    def _build_node_detail(self, state: GraphReasoningState, node: GraphNodeState) -> NodeDetailResponse:
        prepared = self._prepared_node(state, node)
        patch_history = self._patch_history_for_node(state, node.id)
        return NodeDetailResponse(
            task_id=state.task_id,
            node=prepared,
            key_conclusion=self._key_conclusion_for_node(prepared),
            evidence_count=len(prepared.evidence_refs),
            top_evidence=prepared.evidence_refs[:3],
            finding_records=prepared.finding_records,
            approval_state=prepared.approval_state,
            delegated_children=prepared.delegated_children,
            delegated_summaries=list(node.metadata.get("delegated_summaries", [])),
            patch_history=patch_history,
            technical_details={
                "inputs": node.inputs,
                "output": node.output,
                "verification_checks": prepared.verification_checks,
                "model_metadata": ui_model_metadata(node.model_metadata),
                "evidence_scope": node.evidence_scope,
            },
        )

    @staticmethod
    def _normalize_final_output(state: GraphReasoningState) -> dict[str, Any]:
        current = state.final_output if isinstance(state.final_output, dict) else {}

        def normalized_string(value: Any, fallback: str) -> str:
            if isinstance(value, str) and value.strip() and value.strip() != "...":
                return value.strip()
            return fallback

        def normalized_list(value: Any, fallback: list[str]) -> list[str]:
            if isinstance(value, list):
                items = [
                    item.strip()
                    for item in value
                    if isinstance(item, str) and item.strip() and item.strip() != "..."
                ]
                if items:
                    return items
            return fallback

        thought_summaries = [
            thought.summary.strip()
            for thought in state.thoughts.values()
            if isinstance(thought.summary, str) and thought.summary.strip()
        ]
        evidence_sources = [
            reference.document_id
            for node in state.nodes.values()
            for reference in node.evidence_refs
        ]
        normalized = {
            "objective": normalized_string(current.get("objective"), state.prompt),
            "conclusion": normalized_string(
                current.get("conclusion"),
                "Structured reasoning completed. Human review is recommended before distribution.",
            ),
            "findings": normalized_list(
                current.get("findings"),
                thought_summaries[-3:] or ["Review the reasoning trace for synthesized findings."],
            ),
            "evidence_sources": normalized_list(
                current.get("evidence_sources"),
                evidence_sources[:5] or ["no_evidence_supplied"],
            ),
            "next_steps": normalized_list(
                current.get("next_steps"),
                ["Review the audit package.", "Confirm the final conclusion with a human reviewer."],
            ),
        }
        finding_records = current.get("finding_records")
        if isinstance(finding_records, list) and finding_records:
            normalized["finding_records"] = [
                FindingRecord.model_validate(record).model_dump(mode="json")
                for record in finding_records
            ]
        else:
            derived_records: list[dict[str, Any]] = []
            for index, finding in enumerate(normalized["findings"]):
                matching_refs = []
                for thought in state.thoughts.values():
                    if thought.summary == finding and thought.evidence_refs:
                        matching_refs = thought.evidence_refs
                        break
                support_level = (
                    EvidenceSupportLevel.direct if matching_refs else EvidenceSupportLevel.inferred
                )
                derived_records.append(
                    FindingRecord(
                        id=f"finding_{index + 1}",
                        text=finding,
                        support_level=support_level,
                        claim_classification=(
                            ClaimClassification.grounded
                            if support_level == EvidenceSupportLevel.direct
                            else ClaimClassification.inferred
                        ),
                        evidence_refs=matching_refs,
                    ).model_dump(mode="json")
                )
            normalized["finding_records"] = derived_records
        for key, value in current.items():
            if key not in normalized:
                normalized[key] = value
        return normalized

    def _build_response(self, state: GraphReasoningState, audit_package: dict | None = None) -> TaskRunResponse:
        ordered_nodes = sorted(
            (self._prepared_node(state, node) for node in state.nodes.values()),
            key=lambda node: (
                node.metadata.get("layout", {}).get("row", 999),
                node.metadata.get("layout", {}).get("column", 999),
                node.priority,
            ),
        )
        return TaskRunResponse(
            task_id=state.task_id,
            prompt=state.prompt,
            template_id=state.template_id,
            program_id=state.program_id,
            program_version=state.program_version,
            domain=state.domain,
            deterministic=state.deterministic,
            determinism_mode=state.determinism_mode,
            control_level=state.control_level,
            default_visibility_tier=state.default_visibility_tier,
            status=state.status,
            model_id=state.model_id,
            model_version=state.model_version,
            provider_fingerprint=state.provider_fingerprint,
            execution_endpoint=state.execution_endpoint,
            prompt_hash=state.prompt_hash,
            grs_hash=state.grs_hash,
            execution_env_hash=state.execution_env_hash,
            reproducibility_hash=state.reproducibility_hash,
            created_at=state.created_at,
            completed_at=state.completed_at,
            source_documents=state.source_documents,
            nodes=ordered_nodes,
            edges=state.edges,
            execution_sequence=state.execution_sequence,
            evidence_graph_nodes=state.evidence_graph_nodes,
            evidence_graph_edges=state.evidence_graph_edges,
            prompt_traces=state.prompt_traces,
            graph_patch_history=state.graph_patch_history,
            graph_version_history=state.graph_version_history,
            patch_diff_history=state.patch_diff_history,
            trace_access_history=state.trace_access_history,
            program_blueprint=state.program_blueprint,
            output_schema_definition=state.output_schema_definition,
            final_output=state.final_output,
            final_summary=state.final_summary,
            graph_build_ms=state.graph_build_ms,
            scheduler_metrics_ms=state.scheduler_metrics_ms,
            pending_review_node_id=state.pending_review_node_id,
            review_history=state.review_history,
            schema_validation_logs=state.schema_validation_logs,
            audit_package=audit_package,
        )

    @staticmethod
    def _proposal_requires_approval(state: GraphReasoningState, proposal: PatchProposal) -> bool:
        if proposal.requires_approval:
            return True
        return state.control_level in {ControlLevel.regulated, ControlLevel.strict_audit}

    @staticmethod
    def _apply_execution_overrides(bundle, execution_overrides: dict[str, Any] | None):
        if not execution_overrides:
            return bundle

        policy = execution_overrides.get("policy")
        if isinstance(policy, str) and policy.strip():
            bundle.program.policy = policy.strip()

        instruction_prefix = execution_overrides.get("instruction_prefix")
        if isinstance(instruction_prefix, str) and instruction_prefix.strip():
            prefix = instruction_prefix.strip()
            for node in bundle.program.nodes:
                node.instruction = f"{prefix}\n{node.instruction}".strip()

        evaluation_ids = execution_overrides.get("additional_evaluation_ids")
        if isinstance(evaluation_ids, list) and evaluation_ids:
            additions = [str(value).strip() for value in evaluation_ids if str(value).strip()]
            for node in bundle.program.nodes:
                if node.operation_type in {"analyze", "aggregate", "synthesize"}:
                    node.evaluation_ids = sorted({*node.evaluation_ids, *additions})

        bundle.program.metadata.setdefault("execution_overrides", execution_overrides)
        return bundle

    def _build_controller(
        self,
        task_id: str,
        documents,
        auto_approve_human_review: bool,
    ) -> Controller:
        knowledge_base = KnowledgeBase(documents, task_id=task_id, vector_store=self.vector_store)
        operator = GenericReasoningOperator(knowledge_base, self.llm_gateway, tool_runtime=self.tool_runtime)
        return Controller(
            scheduler=Scheduler(ConstraintInjector()),
            constraints=ConstraintInjector(),
            budget_manager=BudgetManager(),
            audit_store=self.audit_store,
            operation_runner=operator,
            convergence_service=ConvergenceService(),
            evaluation_service=self.evaluation_service,
            schema_service=self.schema_service,
            cache_service=self.cache_service,
            auto_approve_human_review=auto_approve_human_review,
        )

    def _finalize_state(self, state: GraphReasoningState, provider_metadata: dict[str, Any]) -> None:
        if state.final_output is not None:
            state.final_output = self._normalize_final_output(state)
            self._validate_final_findings(state)
            try:
                validate(instance=state.final_output, schema=state.output_schema_definition or {})
            except Exception as exc:
                state.status = TaskStatus.failed
                state.logs.append(ExecutionLogEntry(event="schema_validation_failed", message=str(exc)))
        elif state.status == TaskStatus.completed:
            state.status = TaskStatus.failed
            state.logs.append(
                ExecutionLogEntry(
                    event="missing_final_output",
                    message="Execution completed without a final report payload.",
                )
            )

        if state.prompt_traces:
            latest_trace = state.prompt_traces[-1]
            state.model_id = latest_trace.model_id
            state.model_version = latest_trace.model_version
            state.provider_fingerprint = latest_trace.provider_fingerprint
            state.execution_endpoint = latest_trace.endpoint
        else:
            state.model_id = str(provider_metadata.get("model_id") or state.model_id)
            state.model_version = str(provider_metadata.get("model_version") or state.model_version)
            state.provider_fingerprint = str(provider_metadata.get("provider_fingerprint") or state.provider_fingerprint)
            state.execution_endpoint = provider_metadata.get("endpoint") or state.execution_endpoint

        state.execution_env_hash = build_execution_env_hash(self.settings, state.determinism_mode.value, provider_metadata)
        state.grs_hash = compute_grs_hash(state)
        state.reproducibility_hash = compute_reproducibility_hash(state, provider_metadata)

    @staticmethod
    def _validate_final_findings(state: GraphReasoningState) -> None:
        finding_records = state.final_output.get("finding_records", []) if isinstance(state.final_output, dict) else []
        for raw_record in finding_records:
            record = FindingRecord.model_validate(raw_record)
            if not record.evidence_refs and record.support_level not in {
                EvidenceSupportLevel.inferred,
                EvidenceSupportLevel.unsupported,
                EvidenceSupportLevel.user_provided,
            }:
                raise ValueError(f"Finding {record.id} is missing linked evidence and is not explicitly labeled.")

    def _apply_control_requirements(self, state: GraphReasoningState, auto_approve_human_review: bool) -> None:
        for node in state.nodes.values():
            if node.executor_type.value == "human_operator":
                node.required_approvals = max(node.required_approvals, 1)
                node.metadata["requires_human_review"] = True
            if self._is_high_stakes_node(node):
                node.metadata["high_stakes"] = True
                if state.control_level == ControlLevel.regulated:
                    node.required_approvals = max(node.required_approvals, 1)
                if state.control_level == ControlLevel.strict_audit:
                    node.required_approvals = max(node.required_approvals, 2)
                    node.metadata["requires_human_review"] = True
            if not auto_approve_human_review and (node.operation_type == "synthesize" or not node.next_nodes):
                node.required_approvals = max(node.required_approvals, 1)
                node.metadata["requires_human_review"] = True

    @staticmethod
    def _is_high_stakes_node(node: GraphNodeState) -> bool:
        combined = f"{node.title} {node.subtitle} {node.instruction}".lower()
        keywords = [
            "final audit opinion",
            "material weakness",
            "fraud",
            "regulatory non-compliance",
            "regulatory non compliance",
            "audit opinion",
            "final synthesis",
        ]
        return node.operation_type == "synthesize" or any(keyword in combined for keyword in keywords)

    @staticmethod
    def _resolve_execution_controls(
        deterministic: bool,
        determinism_mode: DeterminismMode | None,
        control_level: ControlLevel,
        auto_approve_human_review: bool,
    ) -> tuple[DeterminismMode, bool, ReasoningVisibilityTier]:
        if determinism_mode is None:
            if control_level == ControlLevel.strict_audit:
                determinism_mode = DeterminismMode.strict_deterministic
            elif deterministic or control_level in {ControlLevel.operational, ControlLevel.regulated}:
                determinism_mode = DeterminismMode.best_effort_deterministic
            else:
                determinism_mode = DeterminismMode.non_deterministic
        if control_level == ControlLevel.strict_audit:
            determinism_mode = DeterminismMode.strict_deterministic

        visibility_tier = {
            ControlLevel.exploratory: ReasoningVisibilityTier.expanded_analytic_trace,
            ControlLevel.operational: ReasoningVisibilityTier.structured_reasoning_trace,
            ControlLevel.regulated: ReasoningVisibilityTier.structured_reasoning_trace,
            ControlLevel.strict_audit: ReasoningVisibilityTier.summary_trace,
        }[control_level]
        auto_approve = auto_approve_human_review and control_level not in {
            ControlLevel.regulated,
            ControlLevel.strict_audit,
        }
        return determinism_mode, auto_approve, visibility_tier

    @staticmethod
    def _cap_visibility_tier(
        control_level: ControlLevel,
        requested_tier: ReasoningVisibilityTier,
    ) -> ReasoningVisibilityTier:
        if control_level == ControlLevel.strict_audit:
            return ReasoningVisibilityTier.summary_trace
        if control_level == ControlLevel.regulated and requested_tier == ReasoningVisibilityTier.expanded_analytic_trace:
            return ReasoningVisibilityTier.structured_reasoning_trace
        return requested_tier

    @staticmethod
    def _approved_count(state: GraphReasoningState, node_id: str) -> int:
        return sum(
            1
            for review in state.review_history
            if review.node_id == node_id and review.decision.lower() in {"approved", "approve"}
        )

    @staticmethod
    def _reset_state_for_replay(state: GraphReasoningState) -> GraphReasoningState:
        clone = GraphReasoningState.model_validate(state.model_dump(mode="json"))
        clone.status = TaskStatus.queued
        clone.started_at = None
        clone.completed_at = None
        clone.final_output = None
        clone.final_summary = None
        clone.pending_review_node_id = None
        clone.execution_sequence = []
        clone.thoughts = {}
        clone.evidence_graph_nodes = {}
        clone.evidence_graph_edges = []
        clone.review_history = []
        clone.evaluation_logs = []
        clone.schema_validation_logs = []
        clone.verification_logs = []
        clone.prompt_traces = [trace for trace in clone.prompt_traces if trace.phase == "program_synthesis"]
        clone.cache_stats = {"hits": 0, "misses": 0}
        clone.budget_usage.tokens_used = 0
        clone.budget_usage.runtime_seconds = 0.0
        clone.budget_usage.nodes_created = len(clone.nodes)
        for node in clone.nodes.values():
            node.status = NodeStatus.pending
            node.verification_status = VerificationStatus.pending
            node.evidence_refs = []
            node.inputs = {}
            node.output = {}
            node.model_metadata = {}
            node.prompt_hash = None
            node.evaluation_score = None
            node.started_at = None
            node.completed_at = None
            node.latency_ms = None
        return clone

    def _require_record(self, task_id: str) -> TaskRunRecord:
        record = self.db.query(TaskRunRecord).filter(TaskRunRecord.task_id == task_id).one_or_none()
        if record is None:
            raise ValueError(f"Task {task_id} not found.")
        return record
