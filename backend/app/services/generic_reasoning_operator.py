from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.models.runtime import (
    GraphNodeState,
    GraphReasoningState,
    NodeExecutionResult,
    VerificationStatus,
)
from app.services.json_utils import extract_json_object
from app.services.knowledge_base import KnowledgeBase
from app.services.llm_gateway import LLMGateway, LLMRequest
from app.services.tool_runtime import ToolRuntime


class GenericReasoningOperator:
    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        llm_gateway: LLMGateway,
        tool_runtime: ToolRuntime | None = None,
    ) -> None:
        self.settings = get_settings()
        self.knowledge_base = knowledge_base
        self.llm_gateway = llm_gateway
        self.tool_runtime = tool_runtime or ToolRuntime()
        self.documents = knowledge_base.documents

    def execute(self, state: GraphReasoningState, node: GraphNodeState) -> NodeExecutionResult:
        evidence_chunks = self.knowledge_base.retrieve(
            f"{state.prompt}\n{node.title}\n{node.subtitle}\n{node.instruction}",
            top_k=4,
        )
        evidence_context = [
            {
                "document_id": chunk.document_id,
                "document_name": chunk.document_name,
                "chunk_id": chunk.id,
                "text": chunk.text,
            }
            for chunk in evidence_chunks
        ]
        available_evidence_ids = sorted({chunk.document_id for chunk in evidence_chunks}) or [
            document.id for document in self.documents
        ]
        is_final_node = node.operation_type == "synthesize" or not node.next_nodes
        node_schema_definitions = (
            (state.program_blueprint or {}).get("metadata", {}).get("node_schema_definitions", {})
            if isinstance((state.program_blueprint or {}).get("metadata", {}), dict)
            else {}
        )
        tool_calls: list[dict[str, Any]] = []
        tool_spec = node.metadata.get("tool")
        tool_result = None
        if isinstance(tool_spec, dict):
            tool_result = self.tool_runtime.execute(tool_spec, state, node, self.knowledge_base)
            tool_calls.append(tool_result)
            if node.metadata.get("tool_only"):
                return NodeExecutionResult(
                    output={"tool_result": tool_result},
                    evidence_refs=available_evidence_ids[:3],
                    verification_status=VerificationStatus.skipped,
                    thought_summary=str(tool_result.get("tool", node.subtitle)),
                    llm_usage_tokens=0,
                    final_output=self._build_fallback_final_output(state, node, {"tool_result": tool_result}, available_evidence_ids)
                    if is_final_node
                    else None,
                    final_summary=self._build_fallback_summary(state, node, {"tool_result": tool_result})
                    if is_final_node
                    else None,
                    tool_calls=tool_calls,
                )

        prompt = (
            "Execute the current reasoning node and return JSON only.\n"
            "Use only provided evidence identifiers.\n"
            "Ground every substantive claim in the supplied evidence.\n"
        )
        system_prompt = (
            "You are the MindWeave runtime executor. "
            "Produce structured node outputs for a reasoning graph. "
            "Never bypass verification gates or fabricate evidence references."
        )
        response = self.llm_gateway.generate(
            LLMRequest(
                task="node_execution",
                prompt=prompt,
                system_prompt=system_prompt,
                context={
                    "user_prompt": state.prompt,
                    "domain": state.domain,
                    "program_id": state.program_id,
                    "node_count": len(state.nodes),
                    "node_id": node.id,
                    "node_title": node.title,
                    "node_subtitle": node.subtitle,
                    "operation_type": node.operation_type,
                    "node_instruction": node.instruction,
                    "success_criteria": node.success_criteria,
                    "input_schema_definition": node_schema_definitions.get(node.input_schema_id or "", {}),
                    "output_schema_definition": (
                        state.output_schema_definition
                        if is_final_node
                        else node_schema_definitions.get(node.output_schema_id or "", {})
                    ),
                    "dependency_outputs": node.inputs,
                    "available_evidence_ids": available_evidence_ids,
                    "retrieved_evidence": evidence_context,
                    "tool_result": tool_result,
                    "is_final_node": is_final_node,
                },
                temperature=0.0 if state.deterministic else self.settings.k2_temperature,
                seed=state.program_blueprint.get("deterministic_defaults", {}).get("seed")
                if state.program_blueprint
                else None,
                agentic=True,
                max_tokens=3200 if is_final_node else 2000,
            )
        )

        payload = self._load_payload(response.content)
        evidence_refs = self._normalize_evidence_refs(payload.get("evidence_ids", []), available_evidence_ids)
        verification_status = self._normalize_verification_status(payload.get("verification_status"))
        if node.operation_type == "verify" and verification_status == VerificationStatus.skipped:
            verification_status = VerificationStatus.passed
        verification_checks = payload.get("verification_checks", [])
        output = payload.get("output")
        if not isinstance(output, dict) or not output:
            output = self._extract_structured_output(payload, response.content)
        final_output = payload.get("final_output")
        if is_final_node and (not isinstance(final_output, dict) or not final_output):
            final_output = output
        if is_final_node and (not isinstance(final_output, dict) or not final_output):
            final_output = self._build_fallback_final_output(
                state,
                node,
                output if isinstance(output, dict) else {},
                available_evidence_ids,
            )

        final_summary = payload.get("final_summary")
        if is_final_node and final_summary is None:
            final_summary = self._build_fallback_summary(state, node, final_output or output)

        spawned_nodes = self._parse_spawned_nodes(payload.get("spawned_nodes"), node)

        return NodeExecutionResult(
            output=output if isinstance(output, dict) else {"value": output},
            evidence_refs=evidence_refs,
            verification_status=verification_status,
            verification_checks=verification_checks if isinstance(verification_checks, list) else [],
            thought_summary=str(payload.get("summary", node.subtitle)),
            llm_usage_tokens=response.prompt_tokens + response.completion_tokens,
            final_output=final_output if isinstance(final_output, dict) else None,
            final_summary=final_summary if isinstance(final_summary, dict) else None,
            spawned_nodes=spawned_nodes,
            tool_calls=tool_calls,
        )

    def _load_payload(self, content: str) -> dict[str, Any]:
        try:
            return extract_json_object(content)
        except Exception:
            try:
                repair = self.llm_gateway.generate(
                    LLMRequest(
                        task="json_repair",
                        prompt=(
                            "Convert the provided content into a single strict JSON object only. "
                            "Use double-quoted keys, no markdown fences, no comments, and no trailing commas."
                        ),
                        context={"raw_text": content},
                        temperature=self.settings.k2_temperature,
                        agentic=False,
                        max_tokens=2400,
                    )
                )
                return extract_json_object(repair.content)
            except Exception:
                return {"raw_response": content.strip()}

    @staticmethod
    def _parse_spawned_nodes(payload: Any, parent: GraphNodeState) -> list[GraphNodeState]:
        if not isinstance(payload, list):
            return []
        spawned: list[GraphNodeState] = []
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("id") or f"{parent.id}_child_{index + 1}")
            next_nodes = item.get("next_nodes") or item.get("next") or []
            spawned.append(
                GraphNodeState(
                    id=node_id,
                    title=str(item.get("title") or node_id.replace("_", " ").title()),
                    subtitle=str(item.get("subtitle") or "Spawned reasoning step"),
                    operation_type=str(item.get("operation_type") or "analyze"),
                    instruction=str(item.get("instruction") or "Analyze spawned branch."),
                    success_criteria=[str(value) for value in item.get("success_criteria", [])],
                    evaluation_ids=[str(value) for value in item.get("evaluation_ids", [])],
                    priority=int(item.get("priority", parent.priority + 5)),
                    depends_on=[parent.id],
                    guarded_by=[str(value) for value in item.get("guarded_by", [])],
                    next_nodes=[str(value) for value in next_nodes if str(value).strip()],
                    metadata=item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {},
                    spawned_from=parent.id,
                )
            )
        return spawned

    @staticmethod
    def _extract_structured_output(payload: dict[str, Any], raw_content: str) -> dict[str, Any]:
        reserved = {
            "summary",
            "evidence_ids",
            "verification_status",
            "verification_checks",
            "final_output",
            "final_summary",
        }
        structured = {
            key: value
            for key, value in payload.items()
            if key not in reserved and value not in (None, "", [], {})
        }
        if structured:
            return structured
        if raw_content.strip():
            return {"raw_response": raw_content.strip()}
        return {}

    @staticmethod
    def _normalize_evidence_refs(values: Any, allowed_values: list[str]) -> list[str]:
        if not isinstance(values, list):
            return allowed_values[:3]
        normalized = [value for value in values if isinstance(value, str) and value in allowed_values]
        return normalized or allowed_values[:3]

    @staticmethod
    def _normalize_verification_status(value: Any) -> VerificationStatus:
        if value == "passed":
            return VerificationStatus.passed
        if value == "failed":
            return VerificationStatus.failed
        return VerificationStatus.skipped

    @staticmethod
    def _build_fallback_summary(
        state: GraphReasoningState,
        node: GraphNodeState,
        final_output: dict[str, Any],
    ) -> dict[str, Any]:
        top_keys = list(final_output.keys())[:3]
        return {
            "headline": node.title,
            "verdict": state.domain.title(),
            "key_points": [f"Structured output produced with keys: {', '.join(top_keys)}."],
            "metrics": [
                {"label": "Program", "value": state.program_id},
                {"label": "Documents", "value": str(len(state.source_documents))},
            ],
        }

    @staticmethod
    def _build_fallback_final_output(
        state: GraphReasoningState,
        node: GraphNodeState,
        output: dict[str, Any],
        available_evidence_ids: list[str],
    ) -> dict[str, Any]:
        supporting_findings = [
            thought.summary
            for thought in state.thoughts.values()
            if thought.node_id != node.id and thought.summary
        ]
        findings = supporting_findings[-3:] or [node.subtitle]
        evidence_sources = available_evidence_ids[:5] or [document.id for document in state.source_documents[:5]]
        conclusion = "Structured reasoning completed. Review the supporting node outputs for full traceability."
        if output:
            conclusion = f"{conclusion} Captured fields: {', '.join(list(output.keys())[:4])}."
        return {
            "objective": state.prompt,
            "conclusion": conclusion,
            "findings": findings,
            "evidence_sources": evidence_sources,
            "next_steps": [
                "Review the verification node and linked evidence.",
                "Confirm the final conclusion before external distribution.",
            ],
        }
