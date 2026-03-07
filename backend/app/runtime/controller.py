from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from app.models.runtime import (
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
        if node.metadata.get("requires_human_review") and not node.metadata.get("review_approved"):
            if self.auto_approve_human_review:
                approval = ReviewDecision(
                    node_id=node.id,
                    reviewer="system:auto-approve",
                    decision="approved",
                    comments="Auto-approved according to task execution settings.",
                )
                state.review_history.append(approval)
                node.metadata["review_approved"] = True
                self._log(state, "human_review_auto_approved", approval.comments, node.id)
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
        node.verification_status = result.verification_status
        node.completed_at = utcnow()
        node.latency_ms = int((node.completed_at - node.started_at).total_seconds() * 1000)
        node.status = NodeStatus.completed
        node.metadata["cache_hit"] = result.cache_hit
        if node.evaluation_ids == []:
            node.evaluation_ids = self.evaluation_service.default_ids_for(node)

        thought_id = f"thought_{node.id}"
        state.thoughts[thought_id] = ThoughtRecord(
            id=thought_id,
            node_id=node.id,
            summary=result.thought_summary or node.subtitle,
            content=result.output,
            evidence_refs=result.evidence_refs,
            depends_on_thoughts=[f"thought_{dependency_id}" for dependency_id in node.depends_on],
        )

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
            for spawned_node in result.spawned_nodes:
                self.constraints.assert_spawn_allowed(state, node.id, spawned_node.id, spawned_node.next_nodes)
                state.nodes[spawned_node.id] = spawned_node
                state.edges.extend(
                    GraphEdge(source=spawned_node.id, target=target_id) for target_id in spawned_node.next_nodes
                )
            self.budget_manager.update_runtime(state)

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
