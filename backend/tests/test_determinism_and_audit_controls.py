import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.runtime import ControlLevel, DeterminismMode, ExecutorType, ReasoningVisibilityTier, TaskStatus, TraceAccessRole
from app.services.llm_gateway import MockProvider
from app.services.task_service import TaskService


def _session_factory(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'determinism.db'}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def test_task_run_includes_determinism_hashes_and_evidence_graph(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
        result = asyncio.run(
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

        assert result.determinism_mode == DeterminismMode.best_effort_deterministic
        assert result.control_level == ControlLevel.operational
        assert result.model_id
        assert result.model_version
        assert result.provider_fingerprint
        assert result.prompt_hash
        assert result.grs_hash
        assert result.execution_env_hash
        assert result.reproducibility_hash
        assert result.prompt_traces
        assert result.prompt_traces[0].request_payload
        assert result.prompt_traces[0].response_payload
        assert result.prompt_traces[0].response_hash
        assert result.evidence_graph_nodes
        assert result.evidence_graph_edges
        assert isinstance(result.final_output, dict)
        assert "finding_records" in result.final_output
        assert result.final_output["finding_records"]


def test_best_effort_deterministic_runs_produce_stable_hashes(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
        first = asyncio.run(
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
        second = asyncio.run(
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

        assert first.prompt_hash == second.prompt_hash
        assert first.grs_hash == second.grs_hash
        assert first.reproducibility_hash == second.reproducibility_hash


def test_run_diff_reports_prompt_and_model_metadata_changes(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
        deterministic_run = asyncio.run(
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
        exploratory_run = asyncio.run(
            service.execute_task(
                prompt="Perform a financial audit for Invisium FY2026",
                deterministic=False,
                determinism_mode=DeterminismMode.non_deterministic,
                control_level=ControlLevel.exploratory,
                auto_approve_human_review=True,
                use_sample_data=True,
                files=[],
            )
        )

        diff = service.diff_runs(deterministic_run.task_id, exploratory_run.task_id)

        assert diff.changed_model_metadata["left"]["determinism_mode"] != diff.changed_model_metadata["right"]["determinism_mode"]
        assert diff.changed_prompts
        assert diff.changed_final_output["changed"] in {True, False}


def test_trace_tier_is_capped_and_graph_patch_history_is_recorded(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
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

        assert run.status == TaskStatus.paused
        trace = service.get_reasoning_trace(
            run.task_id,
            ReasoningVisibilityTier.expanded_analytic_trace,
            viewer_role=TraceAccessRole.viewer,
            viewer_id="ops-viewer",
        )
        assert trace.tier == ReasoningVisibilityTier.summary_trace
        assert trace.metadata["viewer_role"] == "viewer"
        assert trace.metadata["viewer_id"] == "ops-viewer"
        refreshed = service.get_task(run.task_id)
        assert refreshed.trace_access_history
        assert refreshed.trace_access_history[-1].effective_tier == ReasoningVisibilityTier.summary_trace

        patched = service.apply_graph_patch(
            task_id=run.task_id,
            patch_type="change_policy",
            target_node_id=None,
            change_reason="Use breadth-first ordering for review.",
            requested_by="qa",
            approved_by="lead",
            payload={"policy": "breadth_first"},
            auto_rerun=False,
        )

        assert patched.graph_patch_history
        assert patched.graph_patch_history[-1].patch_type == "change_policy"
        assert patched.graph_patch_history[-1].resulting_program_version != run.program_version
        assert patched.graph_version_history[-1].patch_id == patched.graph_patch_history[-1].patch_id
        assert patched.patch_diff_history[-1].patch_id == patched.graph_patch_history[-1].patch_id
        assert patched.patch_diff_history[-1].changed_policy is True
        assert patched.patch_diff_history[-1].after_program_version == patched.program_version


def test_direct_patch_validation_rejects_invalid_expansion_contract(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
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

        target_node_id = run.nodes[0].id
        try:
            service.apply_graph_patch(
                task_id=run.task_id,
                patch_type="expand_node",
                target_node_id=target_node_id,
                change_reason="Use an unsupported expansion contract.",
                requested_by="qa",
                approved_by=None,
                payload={"expansion_contracts": ["expand_unbounded"]},
                auto_rerun=False,
            )
        except ValueError as exc:
            assert "Unsupported expansion contract" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("Expected patch validation to reject the unsupported expansion contract.")


def test_reasoning_trace_includes_claim_classification(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
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

        trace = service.get_reasoning_trace(
            run.task_id,
            ReasoningVisibilityTier.structured_reasoning_trace,
            viewer_role=TraceAccessRole.auditor,
            viewer_id="audit-user",
        )
        claims = [claim for entry in trace.entries for claim in entry.get("claims", [])]

        assert claims
        assert all("claim_classification" in claim for claim in claims)
        assert {claim["claim_classification"] for claim in claims}.issubset(
            {"grounded", "inferred", "calculated", "human_entered"}
        )


def test_node_detail_and_node_scoped_operations_refresh_graph_state(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
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

        target_node_id = run.nodes[1].id
        detail = service.get_node_detail(run.task_id, target_node_id)

        assert detail.node.id == target_node_id
        assert detail.node.thought_summary
        assert detail.approval_state.status in {"not_required", "approved", "pending", "partially_approved"}
        assert detail.technical_details["output"] == detail.node.output

        scoped_plan = service.plan_node_change(
            task_id=run.task_id,
            node_id=target_node_id,
            request_text="expand this node into a delegated subgraph",
            requested_by="qa",
        )

        assert scoped_plan.intent is not None
        assert scoped_plan.intent.target_node_id == target_node_id
        assert scoped_plan.proposal is not None

        expanded = service.apply_graph_patch(
            task_id=run.task_id,
            patch_type="expand_node",
            target_node_id=target_node_id,
            change_reason="Create visible expanded branches.",
            requested_by="qa",
            approved_by=None,
            payload={
                "expansion_contracts": ["expand_subgraph"],
                "expand_subgraph": True,
                "max_child_agents": 2,
                "child_token_budget": 4000,
            },
            auto_rerun=False,
        )

        assert any(node.id.startswith(f"{target_node_id}_expanded_") for node in expanded.nodes)
        assert any(edge.kind == "expanded_branch" for edge in expanded.edges)

        executor_changed = service.change_node_executor(
            task_id=expanded.task_id,
            node_id=target_node_id,
            executor_type=ExecutorType.agent_operator.value,
            executor_profile="forensic",
            max_child_agents=2,
            max_recursion_depth=1,
            child_token_budget=4000,
            delegated_summary_required=True,
            requested_by="qa",
            approved_by=None,
            change_reason="Activate node agent mode.",
            instruction_note="Use a forensic review posture.",
            auto_rerun=False,
        )

        updated_node = next(node for node in executor_changed.nodes if node.id == target_node_id)
        assert updated_node.executor_type == ExecutorType.agent_operator
        assert updated_node.executor_profile == "forensic"
        assert updated_node.max_child_agents == 2


def test_replay_logs_determinism_variance_when_replayed_state_changes(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
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

        patched = service.apply_graph_patch(
            task_id=run.task_id,
            patch_type="change_budget",
            target_node_id=None,
            change_reason="Increase budget before replay.",
            requested_by="qa",
            approved_by="lead",
            payload={"max_tokens": 25000},
            auto_rerun=False,
        )
        service.llm_gateway.provider = MockProvider(
            model_name="deterministic-template",
            model_version="2.0.0",
            fingerprint="changed-provider",
        )
        replayed = service.replay_task(patched.task_id)

        assert any(log["event"] == "determinism_variance_detected" for log in replayed.audit_package["event_log"])
