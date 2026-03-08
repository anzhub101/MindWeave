from __future__ import annotations

from collections import deque
from typing import Any

from app.models.artifacts import BudgetSpec
from app.models.runtime import (
    GraphEdge,
    GraphNodeState,
    GraphPatchRecord,
    GraphReasoningState,
    NodeStatus,
    TaskStatus,
    VerificationStatus,
)


class GraphPatchService:
    def apply(
        self,
        state: GraphReasoningState,
        patch_type: str,
        target_node_id: str | None,
        change_reason: str,
        requested_by: str,
        approved_by: str | None,
        payload: dict[str, Any] | None = None,
        auto_rerun: bool = True,
    ) -> GraphPatchRecord:
        patch_payload = payload or {}
        normalized_type = patch_type.strip().lower()

        if normalized_type == "add_node":
            self._add_node(state, target_node_id, patch_payload)
        elif normalized_type == "remove_node":
            self._remove_node(state, target_node_id)
        elif normalized_type == "rewire_dependency":
            self._rewire_dependency(state, target_node_id, patch_payload)
        elif normalized_type == "rerun_subtree":
            self._reset_subtree(state, target_node_id)
        elif normalized_type == "change_policy":
            self._change_policy(state, patch_payload)
        elif normalized_type == "change_budget":
            self._change_budget(state, patch_payload)
        elif normalized_type == "change_evidence_scope":
            self._change_evidence_scope(state, target_node_id, patch_payload)
        elif normalized_type == "change_executor":
            self._change_executor(state, target_node_id, patch_payload)
        elif normalized_type == "expand_node":
            self._expand_node(state, target_node_id, patch_payload)
        else:
            raise ValueError(f"Unsupported patch type: {patch_type}")

        state.program_version = self._bump_patch_version(state.program_version)
        self._sync_program_blueprint(state)
        patch = GraphPatchRecord(
            patch_type=normalized_type,
            target_node_id=target_node_id,
            change_reason=change_reason,
            requested_by=requested_by,
            approved_by=approved_by,
            payload=patch_payload,
            resulting_program_version=state.program_version,
            auto_rerun=auto_rerun,
        )
        state.graph_patch_history.append(patch)
        return patch

    def _add_node(self, state: GraphReasoningState, target_node_id: str | None, payload: dict[str, Any]) -> None:
        raw_node = payload.get("node", payload)
        if not isinstance(raw_node, dict):
            raise ValueError("add_node requires a node payload.")
        node_id = str(raw_node.get("id") or f"patched_node_{len(state.nodes) + 1}")
        if node_id in state.nodes:
            raise ValueError(f"Node {node_id} already exists.")

        depends_on = [str(value) for value in raw_node.get("depends_on", []) if str(value).strip()]
        if target_node_id and not depends_on:
            depends_on = [target_node_id]
        next_nodes = [str(value) for value in raw_node.get("next_nodes", raw_node.get("next", [])) if str(value).strip()]
        node = GraphNodeState(
            id=node_id,
            title=str(raw_node.get("title") or node_id.replace("_", " ").title()),
            subtitle=str(raw_node.get("subtitle") or "Patched node"),
            operation_type=str(raw_node.get("operation_type") or "analyze"),
            instruction=str(raw_node.get("instruction") or "Execute patched node."),
            success_criteria=[str(value) for value in raw_node.get("success_criteria", [])],
            evaluation_ids=[str(value) for value in raw_node.get("evaluation_ids", [])],
            input_schema_id=raw_node.get("input_schema_id"),
            output_schema_id=raw_node.get("output_schema_id"),
            priority=int(raw_node.get("priority", max((node.priority for node in state.nodes.values()), default=0) + 5)),
            executor_type=raw_node.get("executor_type", "llm_operator"),
            max_child_agents=int(raw_node.get("max_child_agents", 0) or 0),
            max_recursion_depth=int(raw_node.get("max_recursion_depth", 0) or 0),
            expansion_contracts=[str(value) for value in raw_node.get("expansion_contracts", [])],
            required_approvals=int(raw_node.get("required_approvals", 0) or 0),
            depends_on=depends_on,
            guarded_by=[str(value) for value in raw_node.get("guarded_by", [])],
            next_nodes=next_nodes,
            metadata=raw_node.get("metadata", {}) if isinstance(raw_node.get("metadata"), dict) else {},
            evidence_scope=raw_node.get("evidence_scope", {}) if isinstance(raw_node.get("evidence_scope"), dict) else {},
        )
        state.nodes[node_id] = node

        for dependency_id in depends_on:
            if dependency_id not in state.nodes:
                continue
            if node_id not in state.nodes[dependency_id].next_nodes:
                state.nodes[dependency_id].next_nodes.append(node_id)
            state.edges.append(GraphEdge(source=dependency_id, target=node_id))

        for next_node_id in next_nodes:
            if next_node_id in state.nodes and node_id not in state.nodes[next_node_id].depends_on:
                state.nodes[next_node_id].depends_on.append(node_id)
            state.edges.append(GraphEdge(source=node_id, target=next_node_id))

    def _remove_node(self, state: GraphReasoningState, target_node_id: str | None) -> None:
        if not target_node_id or target_node_id not in state.nodes:
            raise ValueError("remove_node requires an existing target_node_id.")
        state.nodes.pop(target_node_id)
        state.edges = [edge for edge in state.edges if edge.source != target_node_id and edge.target != target_node_id]
        for node in state.nodes.values():
            node.depends_on = [value for value in node.depends_on if value != target_node_id]
            node.guarded_by = [value for value in node.guarded_by if value != target_node_id]
            node.next_nodes = [value for value in node.next_nodes if value != target_node_id]
        thought_id = f"thought_{target_node_id}"
        state.thoughts.pop(thought_id, None)
        state.prompt_traces = [trace for trace in state.prompt_traces if trace.node_id != target_node_id]
        removable_graph_nodes = {
            node_id
            for node_id, graph_node in state.evidence_graph_nodes.items()
            if graph_node.metadata.get("node_id") == target_node_id or node_id in {f"claim_{target_node_id}"}
        }
        for node_id in removable_graph_nodes:
            state.evidence_graph_nodes.pop(node_id, None)
        state.evidence_graph_edges = [
            edge
            for edge in state.evidence_graph_edges
            if edge.source not in removable_graph_nodes and edge.target not in removable_graph_nodes
        ]

    def _rewire_dependency(self, state: GraphReasoningState, target_node_id: str | None, payload: dict[str, Any]) -> None:
        if not target_node_id or target_node_id not in state.nodes:
            raise ValueError("rewire_dependency requires an existing target_node_id.")
        target = state.nodes[target_node_id]
        old_dependency = str(payload.get("old_dependency_id") or "")
        new_dependency = str(payload.get("new_dependency_id") or "")
        if old_dependency:
            target.depends_on = [value for value in target.depends_on if value != old_dependency]
            if old_dependency in state.nodes:
                state.nodes[old_dependency].next_nodes = [value for value in state.nodes[old_dependency].next_nodes if value != target_node_id]
        if new_dependency:
            if new_dependency not in target.depends_on:
                target.depends_on.append(new_dependency)
            if new_dependency in state.nodes and target_node_id not in state.nodes[new_dependency].next_nodes:
                state.nodes[new_dependency].next_nodes.append(target_node_id)
        state.edges = [
            edge
            for edge in state.edges
            if not (edge.target == target_node_id and edge.source in {old_dependency, new_dependency})
        ]
        for dependency_id in target.depends_on:
            state.edges.append(GraphEdge(source=dependency_id, target=target_node_id))

    def _reset_subtree(self, state: GraphReasoningState, target_node_id: str | None) -> None:
        if not target_node_id or target_node_id not in state.nodes:
            raise ValueError("rerun_subtree requires an existing target_node_id.")
        descendants = self._subtree_nodes(state, target_node_id)
        for node_id in descendants:
            node = state.nodes[node_id]
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
        for node_id in descendants:
            state.thoughts.pop(f"thought_{node_id}", None)
        state.prompt_traces = [trace for trace in state.prompt_traces if trace.node_id not in descendants]
        removable_graph_nodes = {
            node_id
            for node_id, graph_node in state.evidence_graph_nodes.items()
            if graph_node.metadata.get("node_id") in descendants
        }
        for node_id in removable_graph_nodes:
            state.evidence_graph_nodes.pop(node_id, None)
        state.evidence_graph_edges = [
            edge
            for edge in state.evidence_graph_edges
            if edge.source not in removable_graph_nodes and edge.target not in removable_graph_nodes
        ]
        state.execution_sequence = [node_id for node_id in state.execution_sequence if node_id not in descendants]
        state.final_output = None
        state.final_summary = None
        state.pending_review_node_id = None
        state.status = TaskStatus.queued

    @staticmethod
    def _change_policy(state: GraphReasoningState, payload: dict[str, Any]) -> None:
        policy = str(payload.get("policy") or "").strip()
        if not policy:
            raise ValueError("change_policy requires a policy value.")
        state.program_blueprint = dict(state.program_blueprint or {})
        state.program_blueprint["policy"] = policy

    @staticmethod
    def _change_budget(state: GraphReasoningState, payload: dict[str, Any]) -> None:
        budget = {
            "max_nodes": int(payload.get("max_nodes", state.budget_spec.max_nodes)),
            "max_tokens": int(payload.get("max_tokens", state.budget_spec.max_tokens)),
            "max_runtime_seconds": int(payload.get("max_runtime_seconds", state.budget_spec.max_runtime_seconds)),
        }
        state.budget_spec = BudgetSpec.model_validate(budget)

    @staticmethod
    def _change_evidence_scope(state: GraphReasoningState, target_node_id: str | None, payload: dict[str, Any]) -> None:
        if not target_node_id or target_node_id not in state.nodes:
            raise ValueError("change_evidence_scope requires an existing target_node_id.")
        node = state.nodes[target_node_id]
        node.evidence_scope = {
            **node.evidence_scope,
            **(payload if isinstance(payload, dict) else {}),
        }
        note = str(payload.get("instruction_note") or "").strip()
        if note:
            node.instruction = f"{node.instruction}\n{note}".strip()

    @staticmethod
    def _expand_node(state: GraphReasoningState, target_node_id: str | None, payload: dict[str, Any]) -> None:
        if not target_node_id or target_node_id not in state.nodes:
            raise ValueError("expand_node requires an existing target_node_id.")
        node = state.nodes[target_node_id]
        contracts = payload.get("expansion_contracts", [])
        if isinstance(contracts, list):
            node.expansion_contracts = [str(value) for value in contracts if str(value).strip()]
        node.metadata["delegation_requested"] = bool(payload.get("expand_subgraph", False))
        if node.executor_type == "agent_operator" and node.max_child_agents == 0:
            node.max_child_agents = int(payload.get("max_child_agents", 2))

    @staticmethod
    def _change_executor(state: GraphReasoningState, target_node_id: str | None, payload: dict[str, Any]) -> None:
        if not target_node_id or target_node_id not in state.nodes:
            raise ValueError("change_executor requires an existing target_node_id.")
        node = state.nodes[target_node_id]
        executor_type = str(payload.get("executor_type") or "").strip()
        if not executor_type:
            raise ValueError("change_executor requires an executor_type value.")
        node.executor_type = executor_type
        node.max_child_agents = int(payload.get("max_child_agents", node.max_child_agents or 0) or 0)
        node.max_recursion_depth = int(payload.get("max_recursion_depth", node.max_recursion_depth or 0) or 0)
        if payload.get("executor_profile"):
            node.metadata["executor_profile"] = payload["executor_profile"]
        note = str(payload.get("instruction_note") or "").strip()
        if note:
            node.instruction = f"{node.instruction}\n{note}".strip()

    @staticmethod
    def _subtree_nodes(state: GraphReasoningState, root_id: str) -> set[str]:
        queue = deque([root_id])
        visited: set[str] = set()
        while queue:
            node_id = queue.popleft()
            if node_id in visited or node_id not in state.nodes:
                continue
            visited.add(node_id)
            queue.extend(state.nodes[node_id].next_nodes)
        return visited

    @staticmethod
    def _bump_patch_version(version: str) -> str:
        parts = version.split(".")
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            major, minor, patch = [int(part) for part in parts]
            return f"{major}.{minor}.{patch + 1}"
        return "1.0.1"

    @staticmethod
    def _sync_program_blueprint(state: GraphReasoningState) -> None:
        blueprint = dict(state.program_blueprint or {})
        blueprint["version"] = state.program_version
        blueprint["budget"] = state.budget_spec.model_dump(mode="json")
        blueprint["nodes"] = [
            {
                "id": node.id,
                "title": node.title,
                "subtitle": node.subtitle,
                "operation_type": node.operation_type,
                "instruction": node.instruction,
                "success_criteria": node.success_criteria,
                "evaluation_ids": node.evaluation_ids,
                "input_schema_id": node.input_schema_id,
                "output_schema_id": node.output_schema_id,
                "priority": node.priority,
                "executor_type": getattr(node.executor_type, "value", str(node.executor_type)),
                "max_child_agents": node.max_child_agents,
                "max_recursion_depth": node.max_recursion_depth,
                "expansion_contracts": node.expansion_contracts,
                "required_approvals": node.required_approvals,
                "depends_on": node.depends_on,
                "guarded_by": node.guarded_by,
                "next": node.next_nodes,
                "metadata": node.metadata,
                "evidence_scope": node.evidence_scope,
            }
            for node in state.nodes.values()
        ]
        state.program_blueprint = blueprint
