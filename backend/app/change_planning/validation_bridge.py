from __future__ import annotations

from collections import defaultdict, deque

from app.change_planning.intent_models import PatchProposal, PatchValidationResult, PlannedPatchOperation
from app.models.runtime import ControlLevel, GraphReasoningState
from app.services.graph_patch_service import GraphPatchService


ALLOWED_EXPANSION_CONTRACTS = {
    "expand_summary",
    "expand_evidence",
    "expand_alternatives",
    "expand_counterarguments",
    "expand_calculations",
    "expand_subgraph",
}


class ValidationBridge:
    def __init__(self) -> None:
        self.graph_patch_service = GraphPatchService()

    def validate(self, state: GraphReasoningState, proposal: PatchProposal) -> PatchValidationResult:
        checked_rules = [
            "no_cycles_created",
            "verify_gates_preserved",
            "connected_synthesis_path",
            "budget_limits_respected",
            "expansion_contracts_allowed",
            "executor_change_allowed",
            "approval_escalation_checked",
        ]
        warnings: list[str] = []
        errors: list[str] = []
        simulated = GraphReasoningState.model_validate(state.model_dump(mode="json"))

        for patch in proposal.patches:
            try:
                self.graph_patch_service.apply(
                    simulated,
                    patch_type=patch.patch_type,
                    target_node_id=patch.target_node_id,
                    change_reason=patch.change_reason or "Validation simulation",
                    requested_by="planner-validator",
                    approved_by=None,
                    payload=patch.payload,
                    auto_rerun=False,
                )
            except ValueError as exc:
                errors.append(str(exc))

        if not errors and self._creates_cycle(simulated):
            errors.append("Patch would create a cycle in the graph.")
        if not errors and not self._verify_gates_preserved(simulated):
            errors.append("Patch would remove or bypass required verify gating for synthesis nodes.")
        if not errors and not self._connected_synthesis_path(simulated):
            errors.append("Patch would disconnect the graph from at least one synthesis path.")
        if simulated.budget_spec.max_nodes < len(simulated.nodes):
            errors.append("Patch exceeds the configured max_nodes budget.")
        expansion_errors = self._validate_expansion_contracts(proposal)
        errors.extend(expansion_errors)
        executor_errors, executor_warnings = self._validate_executor_changes(state, proposal)
        errors.extend(executor_errors)
        warnings.extend(executor_warnings)

        if proposal.risk_level == "high":
            warnings.append("This proposal is high risk and should be reviewed before application.")
        if state.control_level == ControlLevel.strict_audit:
            warnings.append("Strict audit tasks require explicit approval before any patch can be applied.")

        status = "valid"
        if errors:
            status = "invalid"
        return PatchValidationResult(
            proposal_id=proposal.proposal_id,
            status=status,
            errors=errors,
            warnings=warnings,
            checked_rules=checked_rules,
            requires_approval=proposal.requires_approval,
            affected_nodes=proposal.affected_node_ids,
        )

    def validate_patch(
        self,
        state: GraphReasoningState,
        patch_type: str,
        target_node_id: str | None,
        payload: dict[str, object] | None = None,
        change_reason: str = "",
    ) -> PatchValidationResult:
        risk_level = (
            "high"
            if patch_type in {"remove_node", "rewire_dependency", "change_executor", "change_policy"}
            else "medium"
            if patch_type in {"add_node", "expand_node", "change_evidence_scope", "change_budget", "insert_node_between"}
            else "low"
        )
        affected_nodes = [target_node_id] if target_node_id else []
        if patch_type == "insert_node_between":
            source_node_id = str((payload or {}).get("source_node_id") or "")
            explicit_target_id = str((payload or {}).get("target_node_id") or "")
            affected_nodes = [
                node_id
                for node_id in {source_node_id, explicit_target_id, target_node_id}
                if node_id
            ]
        proposal = PatchProposal(
            proposal_id=f"direct_{patch_type}",
            intent_id="direct_patch",
            patches=[
                PlannedPatchOperation(
                    patch_type=patch_type,
                    target_node_id=target_node_id,
                    payload=payload or {},
                    change_reason=change_reason or f"Direct patch {patch_type}",
                )
            ],
            summary=f"Direct patch {patch_type}",
            explanation="Validation wrapper for direct graph patch application.",
            affected_node_ids=affected_nodes,
            rerun_scope="subtree" if patch_type == "rerun_subtree" else "none",
            risk_level=risk_level,
            requires_approval=state.control_level in {ControlLevel.regulated, ControlLevel.strict_audit}
            or risk_level == "high",
            planner_confidence=1.0,
            status="proposed",
        )
        return self.validate(state, proposal)

    @staticmethod
    def _creates_cycle(state: GraphReasoningState) -> bool:
        graph = {node.id: list(node.next_nodes) for node in state.nodes.values()}
        visited: set[str] = set()
        in_stack: set[str] = set()

        def visit(node_id: str) -> bool:
            if node_id in in_stack:
                return True
            if node_id in visited:
                return False
            visited.add(node_id)
            in_stack.add(node_id)
            for child_id in graph.get(node_id, []):
                if child_id in state.nodes and visit(child_id):
                    return True
            in_stack.remove(node_id)
            return False

        return any(visit(node_id) for node_id in graph)

    @staticmethod
    def _verify_gates_preserved(state: GraphReasoningState) -> bool:
        for node in state.nodes.values():
            if node.operation_type != "synthesize":
                continue
            guard_nodes = [state.nodes[guard_id] for guard_id in node.guarded_by if guard_id in state.nodes]
            dependency_verify_nodes = [state.nodes[dep_id] for dep_id in node.depends_on if dep_id in state.nodes and state.nodes[dep_id].operation_type == "verify"]
            if not guard_nodes and not dependency_verify_nodes:
                return False
            if guard_nodes and not any(guard.operation_type == "verify" for guard in guard_nodes):
                return False
        return True

    @staticmethod
    def _connected_synthesis_path(state: GraphReasoningState) -> bool:
        roots = [node.id for node in state.nodes.values() if not node.depends_on]
        if not roots:
            return False
        visited: set[str] = set()
        queue = deque(roots)
        while queue:
            node_id = queue.popleft()
            if node_id in visited or node_id not in state.nodes:
                continue
            visited.add(node_id)
            queue.extend(state.nodes[node_id].next_nodes)
        synthesis_nodes = [node.id for node in state.nodes.values() if node.operation_type == "synthesize"]
        return bool(synthesis_nodes) and all(node_id in visited for node_id in synthesis_nodes)

    @staticmethod
    def _validate_expansion_contracts(proposal: PatchProposal) -> list[str]:
        errors: list[str] = []
        for patch in proposal.patches:
            if patch.patch_type != "expand_node":
                continue
            contracts = patch.payload.get("expansion_contracts", [])
            if not isinstance(contracts, list):
                errors.append("Expansion contracts must be provided as a list.")
                continue
            invalid = [str(value) for value in contracts if str(value) not in ALLOWED_EXPANSION_CONTRACTS]
            if invalid:
                errors.append(f"Unsupported expansion contract(s): {', '.join(invalid)}.")
        return errors

    @staticmethod
    def _validate_executor_changes(
        state: GraphReasoningState,
        proposal: PatchProposal,
    ) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []
        for patch in proposal.patches:
            if patch.patch_type != "change_executor":
                continue
            executor_type = str(patch.payload.get("executor_type") or "")
            if executor_type == "agent_operator":
                if state.control_level == ControlLevel.strict_audit:
                    errors.append("Agent delegation is not allowed in strict audit mode.")
                elif state.control_level == ControlLevel.regulated:
                    warnings.append("Agent delegation in regulated mode requires reviewer approval.")
            if executor_type == "human_operator":
                warnings.append("Human operators require review approvals before completion.")
        return errors, warnings
