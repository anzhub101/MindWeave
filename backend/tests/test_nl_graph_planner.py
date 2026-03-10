import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.change_planning.intent_parser import IntentParserService
from app.db.base import Base
from app.models.artifacts import BudgetSpec
from app.models.runtime import (
    ControlLevel,
    DeterminismMode,
    GraphNodeState,
    GraphReasoningState,
    ReasoningVisibilityTier,
)
from app.services.llm_gateway import MockProvider
from app.services.task_service import TaskService


def _session_factory(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'nl-planner.db'}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _use_mock_llm(service: TaskService) -> None:
    service.llm_gateway.provider = MockProvider()


def _ambiguous_state() -> GraphReasoningState:
    return GraphReasoningState(
        task_id="planner-state",
        prompt="Test prompt",
        template_id="template",
        program_id="program",
        program_version="1.0.0",
        deterministic=True,
        determinism_mode=DeterminismMode.best_effort_deterministic,
        control_level=ControlLevel.operational,
        default_visibility_tier=ReasoningVisibilityTier.structured_reasoning_trace,
        budget_spec=BudgetSpec(max_nodes=8, max_tokens=5000, max_runtime_seconds=120),
        nodes={
            "revenue_analysis": GraphNodeState(
                id="revenue_analysis",
                title="Revenue Analysis",
                subtitle="Inspect revenue anomalies",
                operation_type="analyze",
                priority=10,
            ),
            "revenue_validation": GraphNodeState(
                id="revenue_validation",
                title="Revenue Validation",
                subtitle="Validate revenue assertions",
                operation_type="verify",
                priority=20,
            ),
            "synthesis": GraphNodeState(
                id="synthesis",
                title="Final Synthesis",
                subtitle="Produce output",
                operation_type="synthesize",
                priority=30,
                depends_on=["revenue_analysis", "revenue_validation"],
                guarded_by=["revenue_validation"],
            ),
        },
    )


def test_plan_change_builds_valid_executor_proposal_and_audit_history(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
        _use_mock_llm(service)
        run = asyncio.run(
            service.execute_task(
                prompt="Perform a financial audit for Invisium FY2026",
                deterministic=True,
                determinism_mode=DeterminismMode.best_effort_deterministic,
                control_level=ControlLevel.operational,
                auto_approve_human_review=True,
                use_sample_data=True,
                files=[],
            )
        )

        planned = service.plan_change(
            task_id=run.task_id,
            request_text="Use a forensic agent on the analysis node",
            requested_by="qa-reviewer",
        )

        assert planned.status == "proposed"
        assert planned.intent is not None
        assert planned.intent.intent_type == "change_executor"
        assert planned.proposal is not None
        assert planned.proposal.patches[0].patch_type == "change_executor"
        assert planned.validation is not None
        assert planned.validation.status == "valid"

        audit = service.get_audit_package(run.task_id)
        assert audit["change_intents"]
        assert audit["patch_proposals"]
        assert audit["patch_validation_history"]


def test_intent_parser_requests_clarification_for_ambiguous_node_reference() -> None:
    parser = IntentParserService()
    intent = parser.parse(
        task_id="planner-state",
        state=_ambiguous_state(),
        request_text="Re-run the revenue node",
        requested_by="qa-reviewer",
    )

    assert intent.status == "needs_clarification"
    assert intent.resolution is not None
    assert intent.resolution.status == "ambiguous"
    assert len(intent.resolution.candidates) == 2


def test_apply_planned_change_requires_approval_for_strict_audit(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
        _use_mock_llm(service)
        run = asyncio.run(
            service.execute_task(
                prompt="Perform a financial audit for Invisium FY2026",
                deterministic=True,
                determinism_mode=DeterminismMode.strict_deterministic,
                control_level=ControlLevel.strict_audit,
                auto_approve_human_review=True,
                use_sample_data=True,
                files=[],
            )
        )

        planned = service.plan_change(
            task_id=run.task_id,
            request_text="Change the evidence scope on the analysis node to only audited financial statements",
            requested_by="qa-reviewer",
        )

        assert planned.proposal is not None
        with pytest.raises(ValueError, match="requires approval"):
            service.apply_planned_change(run.task_id, planned.proposal.proposal_id, approved_by=None, auto_rerun=False)

        applied = service.apply_planned_change(
            run.task_id,
            planned.proposal.proposal_id,
            approved_by="audit-lead",
            auto_rerun=False,
        )

        patched_target_id = planned.proposal.patches[0].target_node_id
        analysis_node = next(node for node in applied.nodes if node.id == patched_target_id)
        assert analysis_node.evidence_scope is not None
        assert analysis_node.evidence_scope.get("instruction_note")


def test_apply_planned_change_can_insert_new_node(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
        _use_mock_llm(service)
        run = asyncio.run(
            service.execute_task(
                prompt="Perform a financial audit for Invisium FY2026",
                deterministic=True,
                determinism_mode=DeterminismMode.best_effort_deterministic,
                control_level=ControlLevel.operational,
                auto_approve_human_review=True,
                use_sample_data=True,
                files=[],
            )
        )

        planned = service.plan_change(
            task_id=run.task_id,
            request_text="Add an internal controls review node after the analysis node",
            requested_by="qa-reviewer",
        )

        assert planned.proposal is not None
        applied = service.apply_planned_change(
            run.task_id,
            planned.proposal.proposal_id,
            approved_by="ops-lead",
            auto_rerun=False,
        )

        assert any(node.id == "internal_controls_review" for node in applied.nodes)
        assert any(patch.patch_type == "add_node" for patch in applied.graph_patch_history)
