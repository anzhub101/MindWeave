from __future__ import annotations

from typing import Any

from app.models.artifacts import RegistryArtifact
from app.models.runtime import EvaluationLogEntry, GraphNodeState, GraphReasoningState, NodeExecutionResult
from app.services.json_utils import extract_json_object
from app.services.llm_gateway import LLMGateway, LLMRequest


class EvaluationService:
    def __init__(self, registry=None, llm_gateway: LLMGateway | None = None) -> None:
        self.registry = registry
        self.llm_gateway = llm_gateway

    def default_ids_for(self, node: GraphNodeState) -> list[str]:
        if node.operation_type == "verify":
            return ["verification_gate"]
        evaluation_ids = ["output_present"]
        if node.operation_type == "synthesize":
            evaluation_ids.append("final_output_schema")
        return evaluation_ids

    def evaluate(
        self,
        state: GraphReasoningState,
        node: GraphNodeState,
        result: NodeExecutionResult,
    ) -> tuple[bool, list[EvaluationLogEntry]]:
        evaluation_ids = node.evaluation_ids or self.default_ids_for(node)
        logs: list[EvaluationLogEntry] = []
        passed = True

        for evaluation_id in evaluation_ids:
            evaluation_passed, message, details = self._run_rule(evaluation_id, state, node, result)
            passed = passed and evaluation_passed
            logs.append(
                EvaluationLogEntry(
                    node_id=node.id,
                    evaluation_id=evaluation_id,
                    passed=evaluation_passed,
                    message=message,
                    details=details,
                )
            )

        return passed, logs

    def _run_rule(
        self,
        evaluation_id: str,
        state: GraphReasoningState,
        node: GraphNodeState,
        result: NodeExecutionResult,
    ) -> tuple[bool, str, dict[str, Any]]:
        definition = self._evaluation_definition(evaluation_id)
        payload = definition.payload if definition is not None else {}
        evaluator_type = payload.get("evaluator_type", "rule_based")
        if evaluator_type == "llm_based":
            return self._run_llm_evaluator(payload, state, node, result)

        success_rule = payload.get("success_rule", evaluation_id)
        if success_rule == "verification_status_present":
            passed = result.verification_status.value in {"passed", "failed"}
            return passed, "Verification node produced a terminal verification status.", {}

        if success_rule == "final_output_required_fields_present":
            result_payload = result.final_output or result.output
            required = (state.output_schema_definition or {}).get("required", [])
            missing = [field for field in required if result_payload.get(field) in (None, "", [], {})]
            return not missing, "Final output contains required schema fields.", {"missing_fields": missing}

        result_payload = result.final_output or result.output
        passed = bool(result_payload)
        return passed, "Node produced a non-empty output payload.", {}

    def _evaluation_definition(self, evaluation_id: str) -> RegistryArtifact | None:
        if self.registry is None:
            return None
        try:
            return self.registry.get("evaluation", evaluation_id)
        except Exception:
            return None

    def _run_llm_evaluator(
        self,
        payload: dict[str, Any],
        state: GraphReasoningState,
        node: GraphNodeState,
        result: NodeExecutionResult,
    ) -> tuple[bool, str, dict[str, Any]]:
        if self.llm_gateway is None:
            return True, "LLM evaluator skipped because no gateway is configured.", {"skipped": True}

        prompt = payload.get("prompt_template") or (
            "Assess whether the node output is consistent and grounded. "
            "Return strict JSON with keys: passed (boolean), message (string)."
        )
        response = self.llm_gateway.generate(
            LLMRequest(
                task="evaluation",
                prompt=prompt,
                context={
                    "user_prompt": state.prompt,
                    "node_id": node.id,
                    "operation_type": node.operation_type,
                    "node_output": result.final_output or result.output,
                    "evidence_refs": result.evidence_refs,
                },
                temperature=0.0,
                agentic=False,
                max_tokens=300,
            )
        )
        try:
            data = extract_json_object(response.content)
        except Exception:
            data = {"passed": bool(result.final_output or result.output), "message": response.content.strip()[:200]}

        passed = bool(data.get("passed"))
        message = str(data.get("message") or "LLM evaluation completed.")
        return passed, message, {"provider": response.provider, "model": response.model}
