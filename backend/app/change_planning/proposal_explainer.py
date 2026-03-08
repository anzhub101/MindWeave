from __future__ import annotations

from app.change_planning.intent_models import ChangeIntent, PatchProposal


class ProposalExplainer:
    def explain(self, intent: ChangeIntent, proposal: PatchProposal) -> str:
        target = intent.target_node_id or "the graph"
        if intent.intent_type == "expand_node":
            return (
                f"This proposal will expand {target}, preserve the existing graph structure, "
                f"and rerun the affected subtree without mutating unrelated branches."
            )
        if intent.intent_type == "rerun_subtree":
            return f"This proposal will rerun only the subtree rooted at {target} and leave the rest of the graph unchanged."
        if intent.intent_type == "add_node":
            return (
                f"This proposal will insert a new node near {target}, rewire only the impacted dependencies, "
                f"and rerun the affected path."
            )
        if intent.intent_type == "change_evidence_scope":
            return f"This proposal will tighten evidence scope for {target} and rerun the affected reasoning path."
        if intent.intent_type == "change_executor":
            return f"This proposal will change how {target} executes and rerun the impacted subtree."
        if intent.intent_type == "change_policy":
            return "This proposal will change the graph-level policy without directly mutating node content."
        if intent.intent_type == "change_budget":
            return "This proposal will update graph budget limits and preserve the existing node topology."
        if intent.intent_type == "rewire_dependency":
            return f"This proposal will rewire dependencies around {target}, validate graph safety, and rerun the impacted subtree."
        if intent.intent_type == "remove_node":
            return f"This proposal will remove {target} from the graph and preserve only the remaining valid execution path."
        return "This proposal translates the natural language request into structured graph patches for review before application."
