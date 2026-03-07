from __future__ import annotations

from app.models.runtime import GraphNodeState, GraphReasoningState, NodeStatus
from app.runtime.constraints import ConstraintInjector


class Scheduler:
    def __init__(self, constraints: ConstraintInjector) -> None:
        self.constraints = constraints

    def ready_nodes(self, state: GraphReasoningState) -> list[GraphNodeState]:
        ready: list[GraphNodeState] = []
        for node in state.nodes.values():
            if node.status != NodeStatus.pending:
                continue
            if self.constraints.block_reason(state, node) is None:
                ready.append(node)
        return self._sort_ready_nodes(state, ready)

    @staticmethod
    def pending_nodes(state: GraphReasoningState) -> list[GraphNodeState]:
        return [node for node in state.nodes.values() if node.status == NodeStatus.pending]

    @staticmethod
    def _sort_ready_nodes(state: GraphReasoningState, ready: list[GraphNodeState]) -> list[GraphNodeState]:
        policy = (state.program_blueprint or {}).get("policy", "priority_based")
        if policy == "breadth_first":
            return sorted(
                ready,
                key=lambda node: (
                    node.metadata.get("layout", {}).get("row", 999),
                    node.metadata.get("layout", {}).get("column", 999),
                    node.id,
                ),
            )
        if policy == "cost_aware":
            return sorted(
                ready,
                key=lambda node: (
                    node.metadata.get("estimated_cost", 0),
                    node.priority,
                    node.id,
                ),
            )
        return sorted(ready, key=lambda node: (node.priority, node.id))
