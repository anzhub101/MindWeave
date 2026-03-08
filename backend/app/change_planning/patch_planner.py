from __future__ import annotations

import re

from app.change_planning.intent_models import ChangeIntent, PatchProposal, PlannedPatchOperation
from app.change_planning.proposal_explainer import ProposalExplainer
from app.models.runtime import ControlLevel, GraphReasoningState


class PatchPlannerService:
    def __init__(self) -> None:
        self.explainer = ProposalExplainer()

    def build(self, state: GraphReasoningState, intent: ChangeIntent) -> PatchProposal:
        patches = self._patches_for_intent(state, intent)
        affected_node_ids = self._affected_nodes(intent, patches)
        risk_level = self._risk_level(state, intent, patches)
        requires_approval = self._requires_approval(state.control_level, risk_level)
        proposal = PatchProposal(
            proposal_id=f"proposal_{intent.intent_id.split('_')[-1]}",
            intent_id=intent.intent_id,
            patches=patches,
            summary=self._summary(intent, patches),
            affected_node_ids=affected_node_ids,
            rerun_scope="subtree" if any(patch.patch_type == "rerun_subtree" for patch in patches) else "none",
            risk_level=risk_level,
            requires_approval=requires_approval,
            planner_confidence=intent.confidence,
        )
        proposal.explanation = self.explainer.explain(intent, proposal)
        return proposal

    def _patches_for_intent(self, state: GraphReasoningState, intent: ChangeIntent) -> list[PlannedPatchOperation]:
        if intent.intent_type == "expand_node":
            return [
                PlannedPatchOperation(
                    patch_type="expand_node",
                    target_node_id=intent.target_node_id,
                    payload=intent.payload,
                    change_reason=intent.reason,
                ),
                PlannedPatchOperation(
                    patch_type="rerun_subtree",
                    target_node_id=intent.target_node_id,
                    payload={"reason": "Expansion requires subtree rerun."},
                    change_reason="Rerun the affected subtree after expansion.",
                ),
            ]
        if intent.intent_type == "rerun_subtree":
            return [
                PlannedPatchOperation(
                    patch_type="rerun_subtree",
                    target_node_id=intent.target_node_id,
                    payload=intent.payload,
                    change_reason=intent.reason,
                )
            ]
        if intent.intent_type == "add_node":
            return self._add_node_plan(state, intent)
        if intent.intent_type == "remove_node":
            return [
                PlannedPatchOperation(
                    patch_type="remove_node",
                    target_node_id=intent.target_node_id,
                    change_reason=intent.reason,
                )
            ]
        if intent.intent_type == "change_policy":
            return [
                PlannedPatchOperation(
                    patch_type="change_policy",
                    payload=intent.payload,
                    change_reason=intent.reason,
                )
            ]
        if intent.intent_type == "change_budget":
            return [
                PlannedPatchOperation(
                    patch_type="change_budget",
                    payload=intent.payload,
                    change_reason=intent.reason,
                )
            ]
        if intent.intent_type == "change_evidence_scope":
            target_ids = [intent.target_node_id] if intent.target_node_id else self._evidence_scope_targets(state)
            patches: list[PlannedPatchOperation] = []
            for node_id in target_ids:
                patches.append(
                    PlannedPatchOperation(
                        patch_type="change_evidence_scope",
                        target_node_id=node_id,
                        payload=intent.payload,
                        change_reason=intent.reason,
                    )
                )
                patches.append(
                    PlannedPatchOperation(
                        patch_type="rerun_subtree",
                        target_node_id=node_id,
                        payload={"reason": "Evidence scope changed."},
                        change_reason="Rerun the affected subtree after evidence scope update.",
                    )
                )
            return patches
        if intent.intent_type == "change_executor":
            return [
                PlannedPatchOperation(
                    patch_type="change_executor",
                    target_node_id=intent.target_node_id,
                    payload=intent.payload,
                    change_reason=intent.reason,
                ),
                PlannedPatchOperation(
                    patch_type="rerun_subtree",
                    target_node_id=intent.target_node_id,
                    payload={"reason": "Executor changed."},
                    change_reason="Rerun the subtree after executor change.",
                ),
            ]
        if intent.intent_type == "rewire_dependency":
            return [
                PlannedPatchOperation(
                    patch_type="rewire_dependency",
                    target_node_id=intent.target_node_id,
                    payload=intent.payload,
                    change_reason=intent.reason,
                ),
                PlannedPatchOperation(
                    patch_type="rerun_subtree",
                    target_node_id=intent.target_node_id,
                    payload={"reason": "Dependencies rewired."},
                    change_reason="Rerun the subtree after dependency rewiring.",
                ),
            ]
        return []

    def _add_node_plan(self, state: GraphReasoningState, intent: ChangeIntent) -> list[PlannedPatchOperation]:
        target_node_id = intent.target_node_id
        node_payload = dict(intent.payload.get("node", {}))
        node_id = str(node_payload.get("id") or f"patched_node_{len(state.nodes) + 1}")
        node_payload["id"] = node_id

        if target_node_id is None:
            synth_nodes = [node for node in state.nodes.values() if node.operation_type == "synthesize"]
            if synth_nodes:
                target_node_id = sorted(synth_nodes, key=lambda node: (node.priority, node.id))[0].id
                intent.target_node_id = target_node_id

        target = state.nodes.get(target_node_id) if target_node_id else None
        insert_before = bool(intent.payload.get("insert_before_target"))
        if target is not None and target.operation_type == "synthesize":
            insert_before = True

        patches: list[PlannedPatchOperation] = []
        if target is None:
            patches.append(
                PlannedPatchOperation(
                    patch_type="add_node",
                    payload={"node": node_payload},
                    change_reason=intent.reason,
                )
            )
            return patches

        if insert_before:
            node_payload.setdefault("depends_on", list(target.depends_on))
            node_payload.setdefault("next", [target.id])
            patches.append(
                PlannedPatchOperation(
                    patch_type="add_node",
                    target_node_id=None,
                    payload={"node": node_payload},
                    change_reason=intent.reason,
                )
            )
            for dependency_id in target.depends_on:
                patches.append(
                    PlannedPatchOperation(
                        patch_type="rewire_dependency",
                        target_node_id=target.id,
                        payload={
                            "old_dependency_id": dependency_id,
                            "new_dependency_id": node_id,
                        },
                        change_reason=f"Insert {node_id} before {target.id}.",
                    )
                )
            rerun_target = node_id
        else:
            node_payload.setdefault("depends_on", [target.id])
            node_payload.setdefault("next", list(target.next_nodes))
            patches.append(
                PlannedPatchOperation(
                    patch_type="add_node",
                    target_node_id=target.id,
                    payload={"node": node_payload},
                    change_reason=intent.reason,
                )
            )
            for next_node_id in target.next_nodes:
                patches.append(
                    PlannedPatchOperation(
                        patch_type="rewire_dependency",
                        target_node_id=next_node_id,
                        payload={
                            "old_dependency_id": target.id,
                            "new_dependency_id": node_id,
                        },
                        change_reason=f"Insert {node_id} between {target.id} and {next_node_id}.",
                    )
                )
            rerun_target = node_id

        patches.append(
            PlannedPatchOperation(
                patch_type="rerun_subtree",
                target_node_id=rerun_target,
                payload={"reason": "Node insertion changed the execution path."},
                change_reason="Rerun the affected subtree after inserting the new node.",
            )
        )
        return patches

    @staticmethod
    def _evidence_scope_targets(state: GraphReasoningState) -> list[str]:
        return [
            node.id
            for node in state.nodes.values()
            if node.operation_type in {"generate", "analyze", "aggregate", "synthesize"}
        ]

    @staticmethod
    def _affected_nodes(intent: ChangeIntent, patches: list[PlannedPatchOperation]) -> list[str]:
        node_ids = [
            patch.target_node_id
            for patch in patches
            if patch.target_node_id
        ]
        if intent.target_node_id:
            node_ids.append(intent.target_node_id)
        add_node_ids = [
            str(patch.payload.get("node", {}).get("id"))
            for patch in patches
            if patch.patch_type == "add_node" and isinstance(patch.payload.get("node"), dict)
        ]
        node_ids.extend(add_node_ids)
        deduped = [node_id for node_id in dict.fromkeys(node_ids) if node_id and node_id != "None"]
        return deduped

    @staticmethod
    def _summary(intent: ChangeIntent, patches: list[PlannedPatchOperation]) -> str:
        patch_count = len(patches)
        target = intent.target_node_id or "graph"
        return f"{intent.intent_type.replace('_', ' ')} plan for {target} with {patch_count} patch operation(s)."

    @staticmethod
    def _risk_level(
        state: GraphReasoningState,
        intent: ChangeIntent,
        patches: list[PlannedPatchOperation],
    ) -> str:
        patch_types = {patch.patch_type for patch in patches}
        if state.control_level == ControlLevel.strict_audit:
            return "high"
        if "remove_node" in patch_types or "rewire_dependency" in patch_types:
            return "high"
        if "change_policy" in patch_types or "change_executor" in patch_types or "add_node" in patch_types:
            return "medium"
        if "fraud" in re.sub(r"\s+", " ", intent.source_text.lower()):
            return "medium"
        return "low"

    @staticmethod
    def _requires_approval(control_level: ControlLevel, risk_level: str) -> bool:
        if control_level == ControlLevel.exploratory:
            return risk_level in {"medium", "high"}
        return True
