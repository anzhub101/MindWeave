from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.change_planning.intent_models import NodeResolutionResult
from app.models.runtime import GraphNodeState, GraphReasoningState


class NodeReferenceResolver:
    def resolve(
        self,
        state: GraphReasoningState,
        source_text: str,
        selected_node_id: str | None = None,
    ) -> NodeResolutionResult:
        query = source_text.strip()
        normalized_query = self._normalize(query)
        if not normalized_query:
            return NodeResolutionResult(
                status="unresolved",
                query=query,
                question="Which node should be changed?",
            )

        if selected_node_id and selected_node_id in state.nodes:
            if any(phrase in normalized_query for phrase in {"this node", "selected node", "current node", "this branch", "this step"}):
                node = state.nodes[selected_node_id]
                return NodeResolutionResult(
                    status="resolved",
                    query=query,
                    target_node_id=node.id,
                    matched_aliases=[node.title],
                    confidence=0.98,
                )

        candidates: list[tuple[float, GraphNodeState, str]] = []
        for node in state.nodes.values():
            best_score = 0.0
            best_alias = ""
            for alias in self._aliases(node):
                score = self._score_alias(normalized_query, alias)
                if score > best_score:
                    best_score = score
                    best_alias = alias
            if best_score > 0:
                candidates.append((best_score, node, best_alias))

        candidates.sort(key=lambda item: (-item[0], item[1].priority, item[1].id))
        if not candidates or candidates[0][0] < 0.42:
            suggestions = [node.id for _, node, _ in candidates[:3]]
            question = "Which node should be changed?"
            if suggestions:
                question = f"Which node should be changed? Candidates: {', '.join(suggestions)}."
            return NodeResolutionResult(
                status="unresolved",
                query=query,
                candidates=suggestions,
                confidence=round(candidates[0][0], 2) if candidates else 0.0,
                question=question,
            )

        if len(candidates) > 1 and candidates[1][0] >= max(candidates[0][0] - 0.08, 0.55):
            top_candidates = [item[1].id for item in candidates[:2]]
            return NodeResolutionResult(
                status="ambiguous",
                query=query,
                candidates=top_candidates,
                matched_aliases=[item[2] for item in candidates[:2] if item[2]],
                confidence=round(candidates[0][0], 2),
                question=f"Did you mean {top_candidates[0]} or {top_candidates[1]}?",
            )

        best_score, best_node, best_alias = candidates[0]
        return NodeResolutionResult(
            status="resolved",
            query=query,
            target_node_id=best_node.id,
            matched_aliases=[best_alias] if best_alias else [],
            confidence=round(best_score, 2),
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", value.lower()).strip()

    def _score_alias(self, normalized_query: str, alias: str) -> float:
        normalized_alias = self._normalize(alias)
        if not normalized_alias:
            return 0.0
        if normalized_alias in normalized_query:
            return 1.0 if len(normalized_alias.split()) > 1 else 0.72
        alias_terms = self._terms(normalized_alias)
        query_terms = self._terms(normalized_query)
        if not alias_terms:
            return 0.0
        overlap = len(alias_terms.intersection(query_terms)) / max(len(alias_terms), 1)
        similarity = SequenceMatcher(None, normalized_query, normalized_alias).ratio()
        return max(overlap * 0.88, similarity * 0.62)

    @staticmethod
    def _terms(value: str) -> set[str]:
        return {term for term in re.findall(r"[a-z0-9]+", value.lower()) if len(term) > 2}

    def _aliases(self, node: GraphNodeState) -> list[str]:
        aliases = {
            node.id,
            node.id.replace("_", " "),
            node.title,
            node.subtitle,
            f"{node.title} node",
            f"{node.title} branch",
            f"{node.subtitle} node",
        }
        if isinstance(node.metadata.get("aliases"), list):
            aliases.update(str(value) for value in node.metadata["aliases"] if str(value).strip())
        title_terms = self._terms(node.title)
        subtitle_terms = self._terms(node.subtitle)
        if title_terms:
            aliases.add(" ".join(sorted(title_terms)))
        if subtitle_terms:
            aliases.add(" ".join(sorted(subtitle_terms)))
        return sorted(alias for alias in aliases if alias and alias.strip())
