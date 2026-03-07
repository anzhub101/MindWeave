from __future__ import annotations

from app.models.artifacts import BudgetSpec, RegistryArtifact
from app.models.runtime import GraphNodeState, GraphReasoningState, NodeExecutionResult
from app.services.evaluation_service import EvaluationService
from app.services.llm_gateway import LLMResponse


class FakeRegistry:
    def get(self, kind: str, artifact_id: str):
        assert kind == "evaluation"
        assert artifact_id == "reasoning_consistency_llm"
        return RegistryArtifact(
            kind="evaluation",
            artifact_id="reasoning_consistency_llm",
            version="1.0.0",
            name="Reasoning Consistency LLM",
            description="LLM evaluation",
            payload={
                "evaluation_id": "reasoning_consistency_llm",
                "evaluator_type": "llm_based",
                "prompt_template": "Return JSON.",
            },
        )


class FakeLLMGateway:
    def generate(self, request):
        return LLMResponse(
            provider="mock",
            model="judge",
            content='{"passed": true, "message": "Grounded enough."}',
            prompt_tokens=10,
            completion_tokens=5,
        )


def test_evaluation_service_supports_llm_based_evaluators():
    state = GraphReasoningState(
        task_id="eval-test",
        prompt="Assess the evidence package.",
        template_id="generated",
        program_id="generated_v1",
        program_version="1.0.0",
        deterministic=True,
        budget_spec=BudgetSpec(max_nodes=4, max_tokens=4000, max_runtime_seconds=60),
    )
    node = GraphNodeState(
        id="synthesis",
        title="Synthesis",
        subtitle="Summarize",
        operation_type="synthesize",
        evaluation_ids=["reasoning_consistency_llm"],
        priority=10,
    )
    result = NodeExecutionResult(output={"summary": "Looks coherent."}, evidence_refs=["doc_1"])

    service = EvaluationService(registry=FakeRegistry(), llm_gateway=FakeLLMGateway())
    passed, logs = service.evaluate(state, node, result)

    assert passed is True
    assert logs[0].evaluation_id == "reasoning_consistency_llm"
    assert logs[0].passed is True
    assert logs[0].message == "Grounded enough."
