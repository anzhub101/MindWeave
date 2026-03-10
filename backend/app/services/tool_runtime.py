from __future__ import annotations

import ast
from typing import Any

from app.models.runtime import GraphNodeState, GraphReasoningState
from app.services.knowledge_base import KnowledgeBase
from app.services.skill_service import SkillService
from app.services.web_search_service import WebSearchService


class ToolRuntime:
    def __init__(self, skill_service: SkillService | None = None) -> None:
        self.web_search = WebSearchService()
        self.skill_service = skill_service

    def execute(
        self,
        tool_spec: dict[str, Any],
        state: GraphReasoningState,
        node: GraphNodeState,
        knowledge_base: KnowledgeBase,
    ) -> dict[str, Any]:
        tool_name = str(tool_spec.get("name", "")).strip().lower()
        args = tool_spec.get("args", {}) if isinstance(tool_spec.get("args"), dict) else {}

        if tool_name == "calculator":
            expression = str(args.get("expression", "0"))
            return {"tool": "calculator", "result": self._safe_eval(expression)}

        if tool_name == "document_lookup":
            name_fragment = str(args.get("name_fragment", node.title))
            documents = knowledge_base.by_name(name_fragment)
            return {
                "tool": "document_lookup",
                "matches": [
                    {"document_id": document.id, "document_name": document.name}
                    for document in documents
                ],
            }

        if tool_name == "evidence_search":
            query = str(args.get("query", f"{state.prompt} {node.title}"))
            top_k = int(args.get("top_k", 3))
            chunks = knowledge_base.retrieve(query, top_k=top_k)
            return {
                "tool": "evidence_search",
                "results": [
                    {
                        "chunk_id": chunk.id,
                        "document_id": chunk.document_id,
                        "document_name": chunk.document_name,
                        "text": chunk.text,
                    }
                    for chunk in chunks
                ],
            }

        if tool_name == "web_search":
            query = str(args.get("query", f"{state.prompt} {node.title}")).strip()
            top_k = int(args.get("top_k", 4))
            results = self.web_search.search(query, top_k=top_k)
            return {
                "tool": "web_search",
                "query": query,
                "provider": self.web_search.settings.web_search_backend,
                "results": [
                    result.model_dump(mode="json")
                    for result in results
                ],
            }

        if tool_name == "skill":
            skill_id = str(args.get("skill_artifact_id", "")).strip()
            if not skill_id:
                return {"tool": "skill", "error": "Missing skill_artifact_id."}
            if self.skill_service is None:
                return {"tool": "skill", "error": "Skill service is unavailable."}
            input_payload = args.get("input_payload", {}) if isinstance(args.get("input_payload"), dict) else {}
            return {
                "tool": "skill",
                "skill_artifact_id": skill_id,
                "result": self.skill_service.run_skill_artifact(skill_id, input_payload=input_payload),
            }

        if tool_name == "dependency_extract":
            dependency_id = str(args.get("dependency_id", ""))
            path = str(args.get("path", ""))
            dependency_output = node.inputs.get(dependency_id, {})
            extracted = self._get_path_value(dependency_output, path)
            if extracted is None and isinstance(dependency_output, dict) and "output" in dependency_output:
                extracted = self._get_path_value(dependency_output.get("output", {}), path)
            return {
                "tool": "dependency_extract",
                "value": extracted,
            }

        return {"tool": tool_name or "unknown", "error": "Unsupported tool."}

    @staticmethod
    def _safe_eval(expression: str) -> float:
        def evaluate(node: ast.AST) -> float:
            if isinstance(node, ast.Expression):
                return evaluate(node.body)
            if isinstance(node, ast.BinOp):
                left = evaluate(node.left)
                right = evaluate(node.right)
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    return left / right
                raise ValueError("Unsupported operator.")
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
                return -evaluate(node.operand)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError("Unsafe calculator expression.")

        return evaluate(ast.parse(expression, mode="eval"))

    @staticmethod
    def _get_path_value(payload: Any, path: str) -> Any:
        if not path:
            return payload
        current = payload
        for part in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current
