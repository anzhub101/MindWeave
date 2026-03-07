from __future__ import annotations

import json
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from jsonschema import validate
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import TaskRunRecord
from app.models.api import TaskRunListItem, TaskRunResponse, TemplateSummary
from app.models.runtime import (
    ExecutionLogEntry,
    GraphEdge,
    GraphNodeState,
    GraphReasoningState,
    ReviewDecision,
    TaskStatus,
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
from app.services.knowledge_base import KnowledgeBase
from app.services.llm_gateway import LLMGateway
from app.services.node_cache import NodeCacheService
from app.services.program_synthesizer import ProgramSynthesisService
from app.services.review_service import ReviewService
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

    async def execute_task(
        self,
        prompt: str,
        deterministic: bool,
        auto_approve_human_review: bool,
        use_sample_data: bool,
        files: list,
        execution_overrides: dict[str, Any] | None = None,
    ) -> TaskRunResponse:
        synthesized = self.program_synthesizer.synthesize(prompt, deterministic=deterministic)
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

        graph_started = perf_counter()
        state = self._instantiate_state(
            task_id=task_id,
            prompt=prompt,
            bundle=synthesized,
            documents=documents,
            deterministic=deterministic,
        )
        state.graph_build_ms = int((perf_counter() - graph_started) * 1000)
        if not auto_approve_human_review:
            final_nodes = [node for node in state.nodes.values() if node.operation_type == "synthesize" or not node.next_nodes]
            if final_nodes:
                final_nodes[-1].metadata["requires_human_review"] = True
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
                event="graph_built",
                message="Graph Reasoning State instantiated.",
                payload={"graph_build_ms": state.graph_build_ms or 0},
            )
        )

        knowledge_base = KnowledgeBase(documents, task_id=task_id, vector_store=self.vector_store)
        operator = GenericReasoningOperator(knowledge_base, self.llm_gateway, tool_runtime=self.tool_runtime)
        controller = Controller(
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

        state = controller.run(state)

        try:
            if state.final_output is not None:
                schema = state.output_schema_definition or {}
                state.final_output = self._normalize_final_output(state)
                validate(instance=state.final_output, schema=schema)
            elif state.status == TaskStatus.completed:
                state.status = TaskStatus.failed
                state.logs.append(
                    ExecutionLogEntry(
                        event="missing_final_output",
                        message="Execution completed without a final report payload.",
                    )
                )
        except Exception as exc:
            state.status = TaskStatus.failed
            state.logs.append(
                ExecutionLogEntry(
                    event="schema_validation_failed",
                    message=str(exc),
                )
            )

        self.audit_store.snapshot(state, "final")
        audit_package, _ = self.audit_store.persist_audit_package(state)
        self._persist_record(state, audit_package)
        return self._build_response(state, audit_package)

    def list_tasks(self) -> list[TaskRunListItem]:
        records = self.db.query(TaskRunRecord).order_by(TaskRunRecord.created_at.desc()).limit(20).all()
        items: list[TaskRunListItem] = []
        for record in records:
            items.append(
                TaskRunListItem(
                    task_id=record.task_id,
                    prompt=record.prompt,
                    status=TaskStatus(record.status),
                    template_id=record.template_id,
                    program_id=record.program_id,
                    domain=record.domain,
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
        return self._build_response(state, record.audit_package)

    def get_audit_package(self, task_id: str) -> dict:
        record = self._require_record(task_id)
        return record.audit_package

    def list_reviews(self, task_id: str) -> list[ReviewDecision]:
        return self.review_service.list_for_task(task_id)

    def submit_review(self, task_id: str, decision: ReviewDecision) -> TaskRunResponse:
        record = self._require_record(task_id)
        state = GraphReasoningState.model_validate(record.grs_snapshot)
        saved_decision = self.review_service.record(task_id, decision)
        state.review_history.append(saved_decision)

        if decision.decision.lower() in {"approved", "approve"}:
            if state.pending_review_node_id:
                node = state.nodes[state.pending_review_node_id]
                node.metadata["review_approved"] = True
            state.pending_review_node_id = None
            state.status = TaskStatus.running
            knowledge_base = KnowledgeBase(state.source_documents, task_id=task_id, vector_store=self.vector_store)
            operator = GenericReasoningOperator(knowledge_base, self.llm_gateway, tool_runtime=self.tool_runtime)
            controller = Controller(
                scheduler=Scheduler(ConstraintInjector()),
                constraints=ConstraintInjector(),
                budget_manager=BudgetManager(),
                audit_store=self.audit_store,
                operation_runner=operator,
                convergence_service=ConvergenceService(),
                evaluation_service=self.evaluation_service,
                schema_service=self.schema_service,
                cache_service=self.cache_service,
                auto_approve_human_review=False,
            )
            state = controller.run(state)
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

        if state.final_output is not None:
            state.final_output = self._normalize_final_output(state)
            try:
                validate(instance=state.final_output, schema=state.output_schema_definition or {})
            except Exception as exc:
                state.status = TaskStatus.failed
                state.logs.append(ExecutionLogEntry(event="schema_validation_failed", message=str(exc)))

        self.audit_store.snapshot(state, "final")
        audit_package, _ = self.audit_store.persist_audit_package(state)
        self._persist_record(state, audit_package)
        return self._build_response(state, audit_package)

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
        deterministic: bool,
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
        return GraphReasoningState(
            task_id=task_id,
            prompt=prompt,
            template_id=bundle.template_id,
            program_id=program.program_id,
            program_version=program.version,
            domain=program.domain,
            deterministic=deterministic,
            requirements_reference_path=bundle.source_requirements_path,
            source_documents=documents,
            nodes=nodes,
            edges=edges,
            budget_spec=program.budget,
            program_blueprint=program.model_dump(mode="json", by_alias=True),
            output_schema_definition=bundle.output_schema_definition,
        )

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
        evidence_sources = [document.id for document in state.source_documents[:5]]
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
            "evidence_sources": normalized_list(current.get("evidence_sources"), evidence_sources or ["no_evidence_supplied"]),
            "next_steps": normalized_list(
                current.get("next_steps"),
                ["Review the audit package.", "Confirm the final conclusion with a human reviewer."],
            ),
        }
        for key, value in current.items():
            if key not in normalized:
                normalized[key] = value
        return normalized

    @staticmethod
    def _build_response(state: GraphReasoningState, audit_package: dict | None = None) -> TaskRunResponse:
        ordered_nodes = sorted(
            state.nodes.values(),
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
            status=state.status,
            created_at=state.created_at,
            completed_at=state.completed_at,
            source_documents=state.source_documents,
            nodes=ordered_nodes,
            edges=state.edges,
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

    def _require_record(self, task_id: str) -> TaskRunRecord:
        record = self.db.query(TaskRunRecord).filter(TaskRunRecord.task_id == task_id).one_or_none()
        if record is None:
            raise ValueError(f"Task {task_id} not found.")
        return record
