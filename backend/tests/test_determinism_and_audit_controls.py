import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.artifacts import BudgetSpec
from app.models.runtime import (
    ControlLevel,
    DeterminismMode,
    DocumentRecord,
    ExecutorType,
    GraphNodeState,
    GraphReasoningState,
    ReasoningVisibilityTier,
    TaskStatus,
    TraceAccessRole,
    VerificationStatus,
)
from app.services.generic_reasoning_operator import GenericReasoningOperator
from app.services.knowledge_base import KnowledgeBase
from app.services.llm_gateway import K2Provider, LLMGateway, LLMRequest, LLMResponse, MockProvider
from app.services.node_chat_service import NodeChatService
from app.services.program_synthesizer import ProgramSynthesisService
from app.services.task_service import TaskService
from app.services.web_search_service import WebSearchResult, WebSearchService


def _session_factory(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'determinism.db'}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _use_mock_llm(service: TaskService) -> None:
    service.llm_gateway.provider = MockProvider()


def test_task_run_includes_determinism_hashes_and_evidence_graph(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
        _use_mock_llm(service)
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
        assert result.planner_trace is not None
        assert result.planner_trace.graph_shape_reason
        assert result.prompt_traces[0].request_payload
        assert result.prompt_traces[0].response_payload
        assert result.prompt_traces[0].response_hash
        assert result.evidence_graph_nodes
        assert result.evidence_graph_edges
        assert result.audit_package["node_reasoning_traces"]
        assert isinstance(result.final_output, dict)
        assert "finding_records" in result.final_output
        assert result.final_output["finding_records"]


def test_planner_trace_is_recorded_without_uploaded_documents(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        WebSearchService,
        "search",
        lambda self, query, top_k=None: [
            WebSearchResult(
                result_id="web_ifrs_1",
                title="IFRS Revenue Recognition Update",
                url="https://example.com/ifrs-revenue-update",
                snippet="Recent SaaS revenue recognition guidance and audit implications.",
                provider="brave_mcp",
            )
        ],
    )

    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
        _use_mock_llm(service)
        result = asyncio.run(
            service.execute_task(
                prompt="Research recent revenue recognition guidance for SaaS vendors",
                deterministic=True,
                determinism_mode=DeterminismMode.best_effort_deterministic,
                control_level=ControlLevel.operational,
                auto_approve_human_review=True,
                use_sample_data=False,
                files=[],
            )
        )

        assert result.planner_trace is not None
        assert result.planner_trace.evidence_sources_available
        assert result.planner_trace.web_fallback_used is True
        assert result.planner_trace.web_search_queries == ["Research recent revenue recognition guidance for SaaS vendors"]
        assert any(source.source_type == "web_search" for source in result.planner_trace.evidence_sources_available)


def test_planner_ignores_empty_uploaded_documents_and_uses_brave_referrals(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        WebSearchService,
        "search",
        lambda self, query, top_k=None: [
            WebSearchResult(
                result_id="web_sec_1",
                title="SEC Staff Accounting Bulletin Update",
                url="https://example.com/sec-sab-update",
                snippet="Staff accounting update relevant to revenue recognition timing.",
                provider="brave_mcp",
            )
        ],
    )

    gateway = LLMGateway()
    gateway.provider = MockProvider()
    synthesizer = ProgramSynthesisService(gateway)
    synthesizer.generated_root = tmp_path / "generated_artifacts"
    blank_document = DocumentRecord(
        id="doc_empty",
        name="empty_upload.txt",
        media_type="text/plain",
        storage_path="uploads/empty_upload.txt",
        text_path="uploads/empty_upload.extracted.txt",
        sha256="abc123",
        extracted_text="   ",
        metadata={"ingest_source": "upload"},
    )

    synthesizer.synthesize(
        "Research recent revenue recognition guidance and cite current sources.",
        documents=[blank_document],
        control_level=ControlLevel.operational.value,
    )

    assert synthesizer.last_planner_trace is not None
    assert synthesizer.last_planner_trace.web_fallback_used is True
    assert any(source.source_type == "web_search" for source in synthesizer.last_planner_trace.evidence_sources_available)


def test_web_search_service_degrades_gracefully_when_lookup_fails() -> None:
    service = WebSearchService()
    service.enabled = lambda: True  # type: ignore[method-assign]
    service.settings.web_search_backend = "brave_api"

    def raise_lookup(*_args, **_kwargs):
        raise RuntimeError("search unavailable")

    service._search_via_brave_api = raise_lookup  # type: ignore[method-assign]

    assert service.search("recent SEC revenue recognition guidance") == []


def test_k2_provider_uses_agent_endpoint_for_agentic_requests(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": "{\"summary\":\"ok\",\"output\":{},\"evidence_ids\":[]}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "system_fingerprint": "agent-endpoint-fingerprint",
            }

    def fake_post(url: str, **_kwargs):
        captured["url"] = url
        return DummyResponse()

    monkeypatch.setattr("app.services.llm_gateway.httpx.post", fake_post)
    provider = K2Provider(
        api_key="test",
        model="MBZUAI-IFM/K2-Think-v2",
        chat_url="https://chat.example/v1/chat/completions",
        agent_url="https://agent.example/v1/chat/completions",
        temperature=0.8,
        reasoning_effort="high",
        top_p=1.0,
    )

    provider.generate(
        LLMRequest(
            task="node_execution",
            prompt="Return JSON only.",
            system_prompt="You are a test agent.",
            context={"node_id": "analysis"},
            agentic=True,
        )
    )

    assert captured["url"] == "https://agent.example/v1/chat/completions"


def test_runtime_execution_anchors_brave_referrals_when_no_documents_are_available() -> None:
    class StubGateway:
        def generate(self, request):
            return LLMResponse(
                provider="k2",
                model="MBZUAI-IFM/K2-Think-v2",
                model_version="MBZUAI-IFM/K2-Think-v2",
                content='{"summary":"Reviewed external guidance.","output":{"findings":["Revenue guidance was reviewed."]},"verification_status":"passed"}',
                prompt_tokens=20,
                completion_tokens=12,
                provider_fingerprint="stub-fingerprint",
                endpoint="https://agent.example/v1/chat/completions",
                request_params={"temperature": request.temperature, "top_p": request.top_p},
                request_payload={"prompt": request.prompt},
                raw={},
            )

    class StubToolRuntime:
        def execute(self, tool_spec, _state, _node, _knowledge_base):
            assert tool_spec["name"] == "web_search"
            return {
                "tool": "web_search",
                "results": [
                    {
                        "result_id": "web_gaap_1",
                        "title": "Current Revenue Recognition Overview",
                        "url": "https://example.com/revenue-overview",
                        "snippet": "Overview of current recognition considerations for SaaS revenue.",
                        "provider": "brave_mcp",
                    }
                ],
            }

    state = GraphReasoningState(
        task_id="runtime-web-fallback",
        prompt="Research current SaaS revenue recognition guidance.",
        template_id="research_template",
        program_id="research_program",
        program_version="1.0.0",
        deterministic=False,
        determinism_mode=DeterminismMode.non_deterministic,
        control_level=ControlLevel.operational,
        budget_spec=BudgetSpec(max_nodes=6, max_tokens=4000, max_runtime_seconds=60),
        program_blueprint={"deterministic_defaults": {"seed": 42}},
        output_schema_definition={"type": "object"},
    )
    node = GraphNodeState(
        id="guidance_review",
        title="Guidance Review",
        subtitle="Anchor the analysis in current external guidance",
        operation_type="analyze",
        instruction="Review current external guidance and summarize the most relevant points.",
        priority=10,
    )
    state.nodes[node.id] = node

    operator = GenericReasoningOperator(
        KnowledgeBase([]),
        llm_gateway=StubGateway(),
        tool_runtime=StubToolRuntime(),
    )
    result = operator.execute(state, node)

    assert any(reference.source_type == "web_search" for reference in result.evidence_refs)
    assert result.model_metadata["web_fallback_used"] is True


def test_node_chat_includes_brave_referrals_in_prompt(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class StubGateway:
        def generate(self, request):
            captured["prompt"] = request.prompt
            captured["context"] = request.context
            return LLMResponse(
                provider="k2",
                model="MBZUAI-IFM/K2-Think-v2",
                model_version="MBZUAI-IFM/K2-Think-v2",
                content="<think>internal analysis</think>\nUse the cited referral and compare it against the node output.",
                prompt_tokens=18,
                completion_tokens=10,
                provider_fingerprint="stub-fingerprint",
                endpoint="https://agent.example/v1/chat/completions",
                request_params={"temperature": request.temperature, "top_p": request.top_p},
                request_payload={"prompt": request.prompt},
                raw={},
            )

    class StubSkillService:
        def run_skill_artifact(self, *_args, **_kwargs):
            return {"ok": True}

    monkeypatch.setattr(
        WebSearchService,
        "search",
        lambda self, query, top_k=None: [
            WebSearchResult(
                result_id="web_referral_1",
                title="IFRS 15 Refresher",
                url="https://example.com/ifrs15-refresher",
                snippet="Practical refresher on IFRS 15 steps for SaaS contracts.",
                provider="brave_mcp",
            )
        ],
    )

    service = NodeChatService(StubGateway(), StubSkillService())
    state = GraphReasoningState(
        task_id="chat-web-fallback",
        prompt="Review current SaaS revenue guidance.",
        template_id="research_template",
        program_id="research_program",
        program_version="1.0.0",
        deterministic=False,
        determinism_mode=DeterminismMode.non_deterministic,
        control_level=ControlLevel.operational,
        budget_spec=BudgetSpec(max_nodes=6, max_tokens=4000, max_runtime_seconds=60),
    )
    node = GraphNodeState(
        id="guidance_review",
        title="Guidance Review",
        subtitle="Current sources are needed",
        operation_type="analyze",
        instruction="Review current guidance and answer questions about it.",
        priority=10,
    )

    result = service.chat(
        state,
        node,
        "Why was this node created, and can you find current sources?",
        history=[{"role": "user", "content": "We have no uploaded guidance yet."}],
    )

    assert result["tool_results"]
    assert "https://example.com/ifrs15-refresher" in str(captured["prompt"])
    assert result["reply"] == "Use the cited referral and compare it against the node output."
    assert isinstance(captured["context"], dict)
    assert captured["context"]["tool_results"]


def test_best_effort_deterministic_runs_produce_stable_hashes(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
        _use_mock_llm(service)
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
        _use_mock_llm(service)
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

        target_node_id = run.nodes[1].id
        detail = service.get_node_detail(run.task_id, target_node_id)

        assert detail.node.id == target_node_id
        assert detail.node.thought_summary
        assert detail.node.reasoning_trace
        assert detail.reasoning_trace == detail.node.reasoning_trace
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
            skill_artifact_id=None,
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


def test_insert_node_between_rewires_edge_and_records_layout_hint(tmp_path) -> None:
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

        edge = run.edges[0]
        inserted = service.apply_graph_patch(
            task_id=run.task_id,
            patch_type="insert_node_between",
            target_node_id=edge.target,
            change_reason="Insert a manual controls review node between two existing steps.",
            requested_by="qa",
            approved_by=None,
            payload={
                "source_node_id": edge.source,
                "target_node_id": edge.target,
                "node": {
                    "id": "manual_controls_review",
                    "title": "Controls Review",
                    "subtitle": "Manual insert for focused controls testing",
                    "operation_type": "verify",
                    "instruction": "Review the inserted controls branch before downstream synthesis.",
                    "executor_type": ExecutorType.agent_operator.value,
                    "required_approvals": 1,
                },
            },
            auto_rerun=False,
        )

        inserted_node = next(node for node in inserted.nodes if node.id == "manual_controls_review")
        source_node = next(node for node in inserted.nodes if node.id == edge.source)
        target_node = next(node for node in inserted.nodes if node.id == edge.target)

        assert inserted_node.depends_on == [edge.source]
        assert inserted_node.next_nodes == [edge.target]
        assert edge.target not in source_node.next_nodes
        assert "manual_controls_review" in source_node.next_nodes
        assert edge.source not in target_node.depends_on
        assert "manual_controls_review" in target_node.depends_on
        assert inserted_node.metadata["layout"]["placement"] == "between_nodes"
        assert any(graph_edge.source == edge.source and graph_edge.target == "manual_controls_review" for graph_edge in inserted.edges)
        assert any(graph_edge.source == "manual_controls_review" and graph_edge.target == edge.target for graph_edge in inserted.edges)


def test_manual_pass_and_verify_resumes_paused_review_node(tmp_path) -> None:
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
                auto_approve_human_review=False,
                use_sample_data=True,
                files=[],
            )
        )

        assert run.status == TaskStatus.paused
        assert run.pending_review_node_id is not None

        resumed = service.pass_and_verify_node(run.task_id, run.pending_review_node_id, reviewer="qa-reviewer")

        updated_node = next(node for node in resumed.nodes if node.id == run.pending_review_node_id)
        assert updated_node.verification_status == VerificationStatus.passed
        assert updated_node.approval_state.approved_count >= updated_node.approval_state.required_approvals
        assert any(review.reviewer == "qa-reviewer" for review in resumed.review_history if review.node_id == updated_node.id)
        assert any(log["event"] == "node_manually_pass_verified" for log in resumed.audit_package["event_log"])


def test_replay_logs_determinism_variance_when_replayed_state_changes(tmp_path) -> None:
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
