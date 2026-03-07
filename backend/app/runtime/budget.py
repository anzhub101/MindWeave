from __future__ import annotations

from datetime import datetime, timezone

from app.models.runtime import GraphReasoningState


class BudgetExceededError(RuntimeError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BudgetManager:
    def assert_can_continue(self, state: GraphReasoningState) -> None:
        self.update_runtime(state)
        if len(state.nodes) > state.budget_spec.max_nodes:
            raise BudgetExceededError("Maximum node budget exceeded.")
        if state.budget_usage.tokens_used > state.budget_spec.max_tokens:
            raise BudgetExceededError("Maximum token budget exceeded.")
        if state.budget_usage.runtime_seconds > state.budget_spec.max_runtime_seconds:
            raise BudgetExceededError("Maximum runtime budget exceeded.")

    def update_runtime(self, state: GraphReasoningState) -> None:
        if state.started_at is None:
            return
        state.budget_usage.runtime_seconds = (utcnow() - state.started_at).total_seconds()
        state.budget_usage.nodes_created = len(state.nodes)

    def record_tokens(self, state: GraphReasoningState, tokens: int) -> None:
        state.budget_usage.tokens_used += tokens

