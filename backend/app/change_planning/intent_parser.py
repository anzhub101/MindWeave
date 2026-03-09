from __future__ import annotations

import re
from uuid import uuid4

from app.change_planning.intent_models import ChangeIntent
from app.change_planning.node_resolver import NodeReferenceResolver
from app.models.runtime import ExecutorType, GraphReasoningState


ALLOWED_EXPANSION_CONTRACTS = {
    "expand_summary",
    "expand_evidence",
    "expand_alternatives",
    "expand_counterarguments",
    "expand_calculations",
    "expand_subgraph",
}


class IntentParserService:
    def __init__(self) -> None:
        self.resolver = NodeReferenceResolver()

    def parse(
        self,
        task_id: str,
        state: GraphReasoningState,
        request_text: str,
        requested_by: str,
        selected_node_id: str | None = None,
    ) -> ChangeIntent:
        normalized = self._normalize(request_text)
        intent_type, reason, base_confidence = self._detect_intent(normalized)
        resolution = None
        payload = self._parse_payload(intent_type, normalized, state, selected_node_id)
        target_scope = self._target_scope(intent_type, normalized, payload)
        target_node_id: str | None = None

        if intent_type in {"change_policy", "change_budget"}:
            target_scope = "graph_wide"
        elif intent_type == "change_evidence_scope" and target_scope == "graph_wide":
            target_node_id = None
        elif intent_type == "add_node" and payload.get("target_optional"):
            target_node_id = selected_node_id if selected_node_id in state.nodes else None
        else:
            resolution = self.resolver.resolve(state, request_text, selected_node_id=selected_node_id)
            target_node_id = resolution.target_node_id

        if intent_type == "add_node" and target_node_id is None:
            synth_nodes = [node for node in state.nodes.values() if node.operation_type == "synthesize"]
            if synth_nodes:
                target_node_id = sorted(synth_nodes, key=lambda node: (node.priority, node.id))[0].id
                if resolution is None:
                    resolution = self.resolver.resolve(state, target_node_id)

        confidence = base_confidence
        status = "proposed"
        if resolution is not None:
            confidence = min(confidence, resolution.confidence or confidence)
            if resolution.status == "ambiguous":
                status = "needs_clarification"
            elif resolution.status == "unresolved" and intent_type not in {"change_policy", "change_budget"}:
                status = "needs_clarification"

        if confidence < 0.55:
            status = "needs_clarification"

        return ChangeIntent(
            intent_id=f"intent_{uuid4().hex[:10]}",
            task_id=task_id,
            requested_by=requested_by,
            intent_type=intent_type,
            target_node_id=target_node_id,
            target_scope=target_scope,
            payload=payload,
            reason=reason,
            confidence=round(confidence, 2),
            source_text=request_text.strip(),
            status=status,
            resolution=resolution,
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", value.lower()).strip()

    def _detect_intent(self, normalized: str) -> tuple[str, str, float]:
        if any(keyword in normalized for keyword in {"expand", "deepen", "drill into"}):
            return "expand_node", "User requested a deeper reasoning expansion for the targeted node.", 0.86
        if any(keyword in normalized for keyword in {"rerun", "re-run", "run again"}):
            return "rerun_subtree", "User requested subtree re-execution.", 0.9
        if any(keyword in normalized for keyword in {"add ", "insert ", "include "}) and any(
            keyword in normalized for keyword in {" node", " review", " check", " branch", "analysis", "controls"}
        ):
            return "add_node", "User requested a new node to be added to the graph.", 0.82
        if any(keyword in normalized for keyword in {"remove", "delete", "drop"}) and (
            "node" in normalized or "branch" in normalized
        ):
            return "remove_node", "User requested removal of a graph node or branch.", 0.78
        if any(keyword in normalized for keyword in {"policy", "breadth", "priority", "cost aware", "cost-aware"}):
            return "change_policy", "User requested a graph-level policy change.", 0.76
        if any(keyword in normalized for keyword in {"budget", "more tokens", "less tokens", "runtime", "max nodes"}):
            return "change_budget", "User requested a change to graph budget limits.", 0.74
        if any(keyword in normalized for keyword in {"evidence", "exclude", "ignore", "restrict", "only audited", "scope"}):
            return "change_evidence_scope", "User requested a change to evidence scope.", 0.84
        if any(keyword in normalized for keyword in {"agent", "executor", "tool operator", "human operator", "human review"}):
            return "change_executor", "User requested a change to node execution mode.", 0.88
        if any(keyword in normalized for keyword in {"depend on", "depends on", "after ", "before ", "route through"}):
            return "rewire_dependency", "User requested a dependency rewiring.", 0.66
        return "rerun_subtree", "The request was interpreted as a scoped rerun.", 0.46

    def _target_scope(self, intent_type: str, normalized: str, payload: dict[str, object]) -> str:
        if intent_type in {"change_policy", "change_budget"}:
            return "graph_wide"
        if intent_type == "change_evidence_scope" and any(keyword in normalized for keyword in {"all ", "only audited", "graph-wide", "entire graph"}):
            return "graph_wide"
        if intent_type in {"expand_node", "rerun_subtree"}:
            return "subtree"
        if payload.get("target_optional"):
            return "graph_wide"
        return "node_local"

    def _parse_payload(
        self,
        intent_type: str,
        normalized: str,
        state: GraphReasoningState,
        selected_node_id: str | None,
    ) -> dict[str, object]:
        if intent_type == "expand_node":
            expansion_contracts = []
            if "evidence" in normalized:
                expansion_contracts.append("expand_evidence")
            if "alternative" in normalized:
                expansion_contracts.append("expand_alternatives")
            if "counter" in normalized:
                expansion_contracts.append("expand_counterarguments")
            if "calculation" in normalized or "recalculate" in normalized:
                expansion_contracts.append("expand_calculations")
            if "summary" in normalized:
                expansion_contracts.append("expand_summary")
            if "branch" in normalized or "subgraph" in normalized:
                expansion_contracts.append("expand_subgraph")
            if not expansion_contracts:
                expansion_contracts = ["expand_subgraph"]
            return {
                "expansion_contracts": [value for value in expansion_contracts if value in ALLOWED_EXPANSION_CONTRACTS],
                "expand_subgraph": "expand_subgraph" in expansion_contracts,
                "max_child_agents": 2 if "agent" in normalized else 0,
                "child_token_budget": 4000 if "agent" in normalized or "subgraph" in normalized else 0,
                "delegated_summary_required": True,
            }
        if intent_type == "rerun_subtree":
            assumption_profile = "conservative" if "conservative" in normalized else "baseline"
            return {
                "assumption_profile": assumption_profile,
                "instruction_note": "Use more conservative assumptions." if assumption_profile == "conservative" else "",
            }
        if intent_type == "add_node":
            label = self._extract_add_node_label(normalized)
            node_id = re.sub(r"[^a-z0-9]+", "_", label).strip("_") or f"patched_node_{len(state.nodes) + 1}"
            operation_type = "verify" if any(keyword in normalized for keyword in {"review", "check", "controls", "control"}) else "analyze"
            insert_before_target = "before " in normalized or "ahead of " in normalized
            return {
                "target_optional": True,
                "insert_before_target": insert_before_target,
                "node": {
                    "id": node_id,
                    "title": label.title(),
                    "subtitle": "Planned from natural language request",
                    "operation_type": operation_type,
                    "instruction": f"Execute the requested {label} step and summarize the result into the graph.",
                    "success_criteria": ["Requested change is addressed", "Output is linked to evidence when applicable"],
                    "evaluation_ids": ["output_present"],
                    "priority": max((node.priority for node in state.nodes.values()), default=0) + 5,
                    "executor_type": ExecutorType.llm_operator.value,
                    "child_token_budget": 0,
                    "delegated_summary_required": False,
                    "metadata": {"planned_from_nl_request": True},
                },
            }
        if intent_type == "change_policy":
            policy = "breadth_first" if "breadth" in normalized else "cost_aware" if "cost" in normalized else "priority_based"
            return {"policy": policy}
        if intent_type == "change_budget":
            payload: dict[str, object] = {}
            token_match = re.search(r"([0-9][0-9,]*)\s+tokens?", normalized)
            runtime_match = re.search(r"([0-9][0-9,]*)\s+seconds?", normalized)
            node_match = re.search(r"([0-9][0-9,]*)\s+nodes?", normalized)
            if token_match:
                payload["max_tokens"] = int(token_match.group(1).replace(",", ""))
            if runtime_match:
                payload["max_runtime_seconds"] = int(runtime_match.group(1).replace(",", ""))
            if node_match:
                payload["max_nodes"] = int(node_match.group(1).replace(",", ""))
            if not payload and any(keyword in normalized for keyword in {"increase", "more"}):
                payload["max_tokens"] = state.budget_spec.max_tokens + 5000
            return payload
        if intent_type == "change_evidence_scope":
            payload: dict[str, object] = {}
            amount_match = re.search(r"under\s+\$?([0-9][0-9,]*(?:\.\d+)?)", normalized)
            if amount_match:
                amount = int(float(amount_match.group(1).replace(",", "")))
                payload["exclude_below_amount"] = amount
                payload["instruction_note"] = f"Ignore items below {amount} unless they are explicitly material."
            if "audited statements" in normalized or "audited financial statements" in normalized:
                matching_documents = [
                    document.id
                    for document in state.source_documents
                    if any(keyword in document.name.lower() for keyword in {"audit", "statement", "financial"})
                ]
                payload["document_ids"] = matching_documents
                payload.setdefault("instruction_note", "Use only audited financial statements as evidence.")
            if "user provided" in normalized:
                payload["source_type"] = "user_provided"
            return payload
        if intent_type == "change_executor":
            if "human" in normalized:
                executor_type = ExecutorType.human_operator.value
            elif "tool" in normalized:
                executor_type = ExecutorType.tool_operator.value
            elif "agent" in normalized:
                executor_type = ExecutorType.agent_operator.value
            else:
                executor_type = ExecutorType.llm_operator.value
            payload = {
                "executor_type": executor_type,
                "max_child_agents": 2 if executor_type == ExecutorType.agent_operator.value else 0,
                "max_recursion_depth": 1 if executor_type == ExecutorType.agent_operator.value else 0,
                "child_token_budget": 4000 if executor_type == ExecutorType.agent_operator.value else 0,
                "delegated_summary_required": executor_type == ExecutorType.agent_operator.value,
            }
            if "forensic" in normalized:
                payload["executor_profile"] = "forensic"
                payload["instruction_note"] = "Use a forensic review posture for this node."
            return payload
        if intent_type == "rewire_dependency":
            payload: dict[str, object] = {}
            dependency_phrase = ""
            if "after " in normalized:
                dependency_phrase = normalized.split("after ", 1)[1]
            elif "through " in normalized:
                dependency_phrase = normalized.split("through ", 1)[1]
            if dependency_phrase:
                resolution = self.resolver.resolve(state, dependency_phrase, selected_node_id=selected_node_id)
                if resolution.target_node_id:
                    payload["new_dependency_id"] = resolution.target_node_id
            return payload
        return {}

    @staticmethod
    def _extract_add_node_label(normalized: str) -> str:
        match = re.search(r"(?:add|insert|include)\s+(?:an?\s+)?(.+?)(?:\s+(?:node|check|review|branch))?$", normalized)
        if not match:
            return "planned review node"
        label = match.group(1).strip()
        for separator in (" after ", " before ", " for ", " on ", " into "):
            if separator in label:
                label = label.split(separator, 1)[0].strip()
                break
        label = re.sub(r"\b(?:the|this|that)\b", "", label).strip()
        label = re.sub(r"\bnode\b$", "", label).strip()
        return label or "planned review node"
