from __future__ import annotations

from app.models.runtime import GraphReasoningState, NodeStatus


class ConvergenceService:
    def is_converged(self, state: GraphReasoningState) -> bool:
        rule = (state.program_blueprint or {}).get("convergence_rule") or "no_pending_nodes"
        pending_nodes = [node for node in state.nodes.values() if node.status == NodeStatus.pending]

        if rule == "no_pending_nodes":
            return not pending_nodes
        if rule == "first_final_output":
            return state.final_output is not None
        if rule == "verification_passed_and_output_ready":
            return state.final_output is not None and any(
                entry.status.value == "passed" for entry in state.verification_logs
            )
        if rule.startswith("min_completed:"):
            try:
                target = int(rule.split(":", 1)[1])
            except ValueError:
                return False
            completed = sum(1 for node in state.nodes.values() if node.status == NodeStatus.completed)
            return completed >= target
        return not pending_nodes
