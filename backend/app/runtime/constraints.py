from __future__ import annotations

from app.models.runtime import GraphNodeState, GraphReasoningState, NodeStatus, VerificationStatus


class ConstraintViolation(RuntimeError):
    pass


class ConstraintInjector:
    def block_reason(self, state: GraphReasoningState, node: GraphNodeState) -> str | None:
        for dependency_id in node.depends_on:
            dependency = state.nodes[dependency_id]
            if dependency.status != NodeStatus.completed:
                return f"Dependency {dependency_id} has not completed."

        for guard_id in node.guarded_by:
            guard = state.nodes[guard_id]
            if guard.status != NodeStatus.completed:
                return f"Verify gate {guard_id} has not completed."
            if guard.verification_status != VerificationStatus.passed:
                return f"Verify gate {guard_id} did not pass."

        return None

    def assert_node_may_run(self, state: GraphReasoningState, node: GraphNodeState) -> None:
        reason = self.block_reason(state, node)
        if reason:
            raise ConstraintViolation(reason)

    def assert_spawn_allowed(
        self,
        state: GraphReasoningState,
        parent_id: str,
        child_id: str,
        child_next_nodes: list[str],
    ) -> None:
        parent = state.nodes[parent_id]
        allowed_targets = set(parent.next_nodes)
        if any(target not in allowed_targets for target in child_next_nodes):
            raise ConstraintViolation(
                f"Node {parent_id} may only spawn descendants within its declared downstream region."
            )
        if child_id in state.nodes:
            raise ConstraintViolation(f"Node {child_id} already exists.")

