from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from app.models.runtime import (
    EvidenceGraphEdge,
    EvidenceGraphNode,
    ExecutionLogEntry,
    GraphEdge,
    GraphNodeState,
    GraphReasoningState,
    NodeStatus,
    ReviewDecision,
    TaskStatus,
    ThoughtRecord,
    VerificationStatus,
    VerificationLogEntry,
)
from app.runtime.audit import AuditStore
from app.runtime.budget import BudgetExceededError, BudgetManager
from app.runtime.constraints import ConstraintInjector
from app.runtime.scheduler import Scheduler
from app.services.convergence import ConvergenceService
from app.services.evaluation_service import EvaluationService
from app.services.schema_service import SchemaService


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HumanReviewRequired(RuntimeError):
    def __init__(self, node_id: str) -> None:
        super().__init__(f"Human review required for node {node_id}.")
        self.node_id = node_id


class Controller:
    def __init__(
        self,
        scheduler: Scheduler,
        constraints: ConstraintInjector,
        budget_manager: BudgetManager,
        audit_store: AuditStore,
        operation_runner: object,
        convergence_service: ConvergenceService | None = None,
        evaluation_service: EvaluationService | None = None,
        schema_service: SchemaService | None = None,
        cache_service=None,
        auto_approve_human_review: bool = True,
    ) -> None:
        self.scheduler = scheduler
        self.constraints = constraints
        self.budget_manager = budget_manager
        self.audit_store = audit_store
        self.operation_runner = operation_runner
        self.convergence_service = convergence_service or ConvergenceService()
        self.evaluation_service = evaluation_service or EvaluationService()
        self.schema_service = schema_service or SchemaService()
        self.cache_service = cache_service
        self.auto_approve_human_review = auto_approve_human_review
        self.execution_cache: dict[str, object] = {}

    def run(self, state: GraphReasoningState) -> GraphReasoningState:
        state.status = TaskStatus.running
        if state.started_at is None:
            state.started_at = utcnow()
        self._log(state, "task_started", "Execution started.")
        self.audit_store.snapshot(state, "started")

        try:
            while True:
                self.budget_manager.assert_can_continue(state)
                scheduler_started = perf_counter()
                ready_nodes = self.scheduler.ready_nodes(state)
                state.scheduler_metrics_ms.append(int((perf_counter() - scheduler_started) * 1000))
                if self.convergence_service.is_converged(state):
                    state.status = TaskStatus.completed
                    state.completed_at = utcnow()
                    self._log(state, "task_completed", "Execution completed due to convergence rule.")
                    break
                if not ready_nodes:
                    pending_nodes = self.scheduler.pending_nodes(state)
                    if not pending_nodes:
                        state.status = TaskStatus.completed
                        state.completed_at = utcnow()
                        self._log(state, "task_completed", "Execution completed.")
                        break

                    for node in pending_nodes:
                        node.status = NodeStatus.blocked
                    state.status = TaskStatus.failed
                    self._log(
                        state,
                        "task_blocked",
                        "Execution halted because pending nodes could not satisfy verification or dependency gates.",
                    )
                    break

                self._execute_node(state, ready_nodes[0])
                self.audit_store.snapshot(state, f"after_{ready_nodes[0].id}")
        except BudgetExceededError as exc:
            state.status = TaskStatus.failed
            self._log(state, "budget_exceeded", str(exc))
        except HumanReviewRequired as exc:
            state.status = TaskStatus.paused
            state.pending_review_node_id = exc.node_id
            self._log(state, "human_review_required", str(exc), exc.node_id)
        except Exception as exc:  # pragma: no cover - keeps failures visible in audit logs
            state.status = TaskStatus.failed
            self._log(state, "task_failed", str(exc))

        if state.status != TaskStatus.completed and state.completed_at is None:
            state.completed_at = utcnow()
        return state

    def _execute_node(self, state: GraphReasoningState, node: GraphNodeState) -> None:
        required_approvals = max(node.required_approvals, 1 if node.metadata.get("requires_human_review") else 0)
        approved_count = self._approved_count(state, node.id)
        if required_approvals and approved_count < required_approvals:
            if self.auto_approve_human_review:
                for index in range(required_approvals - approved_count):
                    approval = ReviewDecision(
                        node_id=node.id,
                        reviewer=f"system:auto-approve:{approved_count + index + 1}",
                        decision="approved",
                        comments="Auto-approved according to task execution settings.",
                    )
                    state.review_history.append(approval)
                    self._log(state, "human_review_auto_approved", approval.comments, node.id)
                node.metadata["review_approved"] = True
            else:
                raise HumanReviewRequired(node.id)

        self.constraints.assert_node_may_run(state, node)
        node.status = NodeStatus.running
        node.started_at = utcnow()
        node.inputs = {
            dependency_id: state.nodes[dependency_id].output for dependency_id in node.depends_on
        }
        input_validation = self.schema_service.validate_node_inputs(state, node)
        if input_validation is not None:
            state.schema_validation_logs.append(input_validation)
            if not input_validation.passed:
                node.status = NodeStatus.failed
                self._log(state, "node_input_schema_failed", input_validation.message, node.id, input_validation.details)
                raise RuntimeError(f"Input schema validation failed for node {node.id}: {input_validation.message}")
        self._log(state, "node_started", f"Executing node {node.id}.", node.id)

        cache_key = self.cache_service.build_key(state, node) if self.cache_service is not None else None
        result = None
        if cache_key and cache_key in self.execution_cache:
            result = self.execution_cache[cache_key]
        elif cache_key and self.cache_service is not None:
            result = self.cache_service.get(cache_key)
        if result is not None:
            result.cache_hit = True
            state.cache_stats["hits"] = state.cache_stats.get("hits", 0) + 1
        else:
            result = self.operation_runner.execute(state, node)
            state.cache_stats["misses"] = state.cache_stats.get("misses", 0) + 1
            if cache_key and self.cache_service is not None:
                self.cache_service.set(cache_key, state, node, result)
                self.execution_cache[cache_key] = result

        evaluation_passed, evaluation_logs = self.evaluation_service.evaluate(state, node, result)
        state.evaluation_logs.extend(evaluation_logs)
        node.output = result.output
        node.evidence_refs = result.evidence_refs
        node.finding_records = result.finding_records
        node.thought_summary = result.thought_summary or node.subtitle
        node.verification_status = result.verification_status
        node.verification_checks = result.verification_checks
        node.model_metadata = result.model_metadata
        node.prompt_hash = result.prompt_trace.prompt_hash if result.prompt_trace is not None else node.prompt_hash
        node.completed_at = utcnow()
        node.latency_ms = int((node.completed_at - node.started_at).total_seconds() * 1000)
        node.status = NodeStatus.completed
        node.metadata["cache_hit"] = result.cache_hit
        if node.evaluation_ids == []:
            node.evaluation_ids = self.evaluation_service.default_ids_for(node)
        if evaluation_logs:
            node.evaluation_score = sum(1.0 if log.passed else 0.0 for log in evaluation_logs) / len(evaluation_logs)

        thought_id = f"thought_{node.id}"
        state.thoughts[thought_id] = ThoughtRecord(
            id=thought_id,
            node_id=node.id,
            summary=result.thought_summary or node.subtitle,
            content=result.output,
            evidence_refs=result.evidence_refs,
            depends_on_thoughts=[f"thought_{dependency_id}" for dependency_id in node.depends_on],
        )
        self._record_evidence_graph(state, node, thought_id, result)
        if result.prompt_trace is not None:
            state.prompt_traces.append(result.prompt_trace)
        state.execution_sequence.append(node.id)

        if result.verification_checks or node.operation_type == "verify":
            state.verification_logs.append(
                VerificationLogEntry(
                    node_id=node.id,
                    status=result.verification_status,
                    checks=result.verification_checks,
                    evidence_refs=result.evidence_refs,
                )
            )

        if not evaluation_passed and node.operation_type == "verify":
            node.verification_status = VerificationStatus.failed

        output_validation = self.schema_service.validate_node_output(state, node, result)
        if output_validation is not None:
            state.schema_validation_logs.append(output_validation)
            if not output_validation.passed:
                node.status = NodeStatus.failed
                self._log(state, "node_output_schema_failed", output_validation.message, node.id, output_validation.details)
                raise RuntimeError(f"Output schema validation failed for node {node.id}: {output_validation.message}")

        if result.final_output is not None:
            state.final_output = result.final_output
        if result.final_summary is not None:
            state.final_summary = result.final_summary

        if result.spawned_nodes:
            spawned_ids: list[str] = []
            for spawned_node in result.spawned_nodes:
                self.constraints.assert_spawn_allowed(state, node.id, spawned_node.id, spawned_node.next_nodes)
                state.nodes[spawned_node.id] = spawned_node
                spawned_ids.append(spawned_node.id)
                spawned_node.executor_profile = spawned_node.executor_profile or spawned_node.metadata.get("executor_profile")
                if spawned_node.id not in node.next_nodes:
                    node.next_nodes.append(spawned_node.id)
                state.edges.append(GraphEdge(source=node.id, target=spawned_node.id, kind="delegated_execution"))
                for target_id in spawned_node.next_nodes:
                    if target_id in state.nodes and spawned_node.id not in state.nodes[target_id].depends_on:
                        state.nodes[target_id].depends_on.append(spawned_node.id)
                state.edges.extend(
                    GraphEdge(source=spawned_node.id, target=target_id) for target_id in spawned_node.next_nodes
                )
            node.metadata["spawned_child_ids"] = sorted(
                set(node.metadata.get("spawned_child_ids", [])) | set(spawned_ids)
            )
            node.delegated_children = sorted(set(node.delegated_children) | set(spawned_ids))
            if node.delegated_summary_required:
                node.metadata["delegation_summary_complete"] = False
            self._log(
                state,
                "delegation_spawned",
                f"Spawned delegated child nodes from {node.id}.",
                node.id,
                {"child_node_ids": spawned_ids},
            )
            self.budget_manager.update_runtime(state)

        if node.spawned_from and node.spawned_from in state.nodes:
            parent = state.nodes[node.spawned_from]
            child_summary = {
                "child_node_id": node.id,
                "summary": result.thought_summary or node.subtitle,
                "output": result.output,
                "finding_records": [record.model_dump(mode="json") for record in result.finding_records],
            }
            delegated_summaries = list(parent.metadata.get("delegated_summaries", []))
            delegated_summaries = [
                item for item in delegated_summaries if item.get("child_node_id") != node.id
            ]
            delegated_summaries.append(child_summary)
            parent.metadata["delegated_summaries"] = delegated_summaries
            if parent.delegated_summary_required:
                spawned_child_ids = set(parent.metadata.get("spawned_child_ids", []))
                completed_child_ids = {
                    child_id
                    for child_id in spawned_child_ids
                    if child_id in state.nodes and state.nodes[child_id].status == NodeStatus.completed
                }
                parent.metadata["delegation_summary_complete"] = spawned_child_ids.issubset(completed_child_ids)
                if parent.metadata["delegation_summary_complete"]:
                    self._log(
                        state,
                        "delegation_completed",
                        f"Delegated child summaries completed for {parent.id}.",
                        parent.id,
                        {"child_node_ids": sorted(spawned_child_ids)},
                    )
            self._log(
                state,
                "delegation_child_summary_recorded",
                f"Recorded delegated child summary from {node.id} back to {parent.id}.",
                node.id,
                {"parent_node_id": parent.id},
            )

        if not result.cache_hit:
            self.budget_manager.record_tokens(state, result.llm_usage_tokens)
            self._log(
                state,
                "node_completed",
                f"Completed node {node.id}.",
                node.id,
            {
                **result.output,
                "cache_hit": result.cache_hit,
                "tool_calls": result.tool_calls,
                "evaluation_passed": evaluation_passed,
            },
        )

    @staticmethod
    def _approved_count(state: GraphReasoningState, node_id: str) -> int:
        return sum(
            1
            for review in state.review_history
            if review.node_id == node_id and review.decision.lower() in {"approved", "approve"}
        )

    @staticmethod
    def _record_evidence_graph(
        state: GraphReasoningState,
        node: GraphNodeState,
        thought_id: str,
        result,
    ) -> None:
        claim_node_id = f"claim_{node.id}"
        state.evidence_graph_nodes[claim_node_id] = EvidenceGraphNode(
            id=claim_node_id,
            kind="claim",
            label=result.thought_summary or node.subtitle,
            metadata={"node_id": node.id, "thought_id": thought_id},
        )
        for evidence in result.evidence_refs:
            evidence_node_id = f"evidence_{evidence.chunk_id}"
            state.evidence_graph_nodes[evidence_node_id] = EvidenceGraphNode(
                id=evidence_node_id,
                kind="evidence",
                label=evidence.document_name or evidence.document_id,
                metadata=evidence.model_dump(mode="json"),
            )
            state.evidence_graph_edges.append(
                EvidenceGraphEdge(
                    source=claim_node_id,
                    target=evidence_node_id,
                    relation="supported_by",
                    metadata={
                        "citation_mode": evidence.citation_mode,
                        "support_level": evidence.support_level.value,
                        "retrieval_score": evidence.retrieval_score,
                    },
                )
            )
        for finding in result.finding_records:
            finding_node_id = f"finding_{finding.id}"
            state.evidence_graph_nodes[finding_node_id] = EvidenceGraphNode(
                id=finding_node_id,
                kind="finding",
                label=finding.text,
                metadata={"node_id": node.id, "support_level": finding.support_level.value},
            )
            state.evidence_graph_edges.append(
                EvidenceGraphEdge(
                    source=finding_node_id,
                    target=claim_node_id,
                    relation="derived_from",
                    metadata={"support_level": finding.support_level.value},
                )
            )
            for evidence in finding.evidence_refs:
                evidence_node_id = f"evidence_{evidence.chunk_id}"
                state.evidence_graph_nodes[evidence_node_id] = EvidenceGraphNode(
                    id=evidence_node_id,
                    kind="evidence",
                    label=evidence.document_name or evidence.document_id,
                    metadata=evidence.model_dump(mode="json"),
                )
                state.evidence_graph_edges.append(
                    EvidenceGraphEdge(
                        source=finding_node_id,
                        target=evidence_node_id,
                        relation="supported_by",
                        metadata={
                            "citation_mode": evidence.citation_mode,
                            "support_level": evidence.support_level.value,
                            "retrieval_score": evidence.retrieval_score,
                        },
                    )
                )

    @staticmethod
    def _log(
        state: GraphReasoningState,
        event: str,
        message: str,
        node_id: str | None = None,
        payload: dict | None = None,
    ) -> None:
        state.logs.append(
            ExecutionLogEntry(
                event=event,
                message=message,
                node_id=node_id,
                payload=payload or {},
            )
        )
