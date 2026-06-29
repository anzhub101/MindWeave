"""Tests for the SPA Contract-to-Cash use case.

Covers:
- Program JSON structure (instruction fields, approval gate)
- deal_brief_schema_v1 validation (valid and invalid payloads)
- Regulated control level enforces auto_approve=False server-side
- SPA program execution pauses at the human_review authority gate
- Node cache invalidate_by_program prunes SQL rows
- Program-version change naturally misses the cache (no stale replay)
"""
import asyncio
import json
from pathlib import Path

import pytest
from jsonschema import validate, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.db.base import Base
from app.models.runtime import (
    ControlLevel,
    DeterminismMode,
    GraphNodeState,
    GraphReasoningState,
    TaskStatus,
)
from app.services.llm_gateway import MockProvider
from app.services.node_cache import NodeCacheService
from app.models.runtime import NodeExecutionResult
from app.services.task_service import TaskService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ARTIFACTS_ROOT = Path(get_settings().artifact_root)
PROGRAM_PATH = ARTIFACTS_ROOT / "programs" / "spa_contract_to_cash_v1.json"
SCHEMA_PATH = ARTIFACTS_ROOT / "schemas" / "deal_brief_schema_v1.json"
TEMPLATE_PATH = ARTIFACTS_ROOT / "templates" / "spa_contract_to_cash_v1.json"


def _session_factory(tmp_path):
    url = f"sqlite:///{tmp_path / 'spa_test.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _use_mock_llm(service: TaskService) -> None:
    service.llm_gateway.provider = MockProvider()


def _load_program() -> dict:
    return json.loads(PROGRAM_PATH.read_text(encoding="utf-8"))


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_template() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


SPA_PROMPT = (
    "Review the SPA for Unit KR-1807 against the approved standard SPA template v3.0. "
    "Identify all clause deviations; validate the payment plan; verify the buyer KYC pack; "
    "check DLD/RERA/escrow compliance. Produce a deal brief with suggested redlines and route "
    "for HOD→FC→SEVC approval."
)


# ---------------------------------------------------------------------------
# 1. SPA program JSON structure
# ---------------------------------------------------------------------------

def test_spa_program_file_exists():
    assert PROGRAM_PATH.exists(), f"Missing: {PROGRAM_PATH}"
    assert SCHEMA_PATH.exists(), f"Missing: {SCHEMA_PATH}"
    assert TEMPLATE_PATH.exists(), f"Missing: {TEMPLATE_PATH}"


def test_spa_program_has_nine_nodes():
    program = _load_program()
    assert len(program["nodes"]) == 9


def test_spa_program_every_node_has_instruction():
    program = _load_program()
    for node in program["nodes"]:
        assert "instruction" in node and node["instruction"], (
            f"Node '{node['id']}' is missing an instruction field"
        )


def test_spa_program_human_review_node_has_required_approvals():
    program = _load_program()
    human_review = next(n for n in program["nodes"] if n["id"] == "human_review")
    assert human_review.get("required_approvals", 0) >= 1
    assert human_review.get("metadata", {}).get("requires_human_review") is True


def test_spa_program_deal_brief_synthesis_is_guarded_by_human_review():
    program = _load_program()
    synthesis = next(n for n in program["nodes"] if n["id"] == "deal_brief_synthesis")
    assert "human_review" in synthesis.get("guarded_by", [])
    assert "human_review" in synthesis.get("depends_on", [])


def test_spa_program_four_parallel_verification_branches():
    program = _load_program()
    term_extraction = next(n for n in program["nodes"] if n["id"] == "term_extraction")
    expected_branches = {"clause_deviation_check", "payment_plan_validation", "kyc_aml_check", "compliance_check"}
    assert expected_branches == set(term_extraction["next"]), (
        f"Expected 4 parallel branches from term_extraction; got {term_extraction['next']}"
    )


def test_spa_program_risk_aggregation_depends_on_all_four_branches():
    program = _load_program()
    risk_agg = next(n for n in program["nodes"] if n["id"] == "risk_aggregation")
    expected = {"clause_deviation_check", "payment_plan_validation", "kyc_aml_check", "compliance_check"}
    assert expected == set(risk_agg["depends_on"])


def test_spa_template_suggests_regulated_control_level():
    template = _load_template()
    assert template.get("suggested_control_level") == "regulated"


def test_spa_template_suggests_best_effort_deterministic():
    template = _load_template()
    assert template.get("suggested_determinism_mode") == "best_effort_deterministic"


# ---------------------------------------------------------------------------
# 2. deal_brief_schema_v1 — valid and invalid payloads
# ---------------------------------------------------------------------------

VALID_DEAL_BRIEF = {
    "recommendation": "HOLD — do not execute. Critical deviations on escrow, jurisdiction, and warranty.",
    "authority_routing": "SEVC + Legal + Compliance",
    "findings": [
        {
            "id": "D1",
            "area": "clause_deviation",
            "severity": "critical",
            "description": "Payments routed to operating account; escrow law absent.",
            "citation": "Deal Cl. 5 vs Standard Cl. 5 (Law No. 8 of 2007)",
            "routes_to": "SEVC + Legal",
        }
    ],
    "payment_validation": {
        "stated_total_pct": 98,
        "computed_total_pct": 98,
        "errors": ["Schedule sums to 98% — 2% / AED 130,000 unallocated"],
    },
    "kyc_flags": ["Source of funds not provided", "Name mismatch"],
    "suggested_redlines": [
        "Cl. 5: Restore mandatory escrow clause referencing Dubai Law No. 8 of 2007.",
        "Cl. 13: Replace Seychelles jurisdiction with Dubai Courts.",
    ],
}


def test_deal_brief_schema_valid_payload_passes():
    schema = _load_schema()
    # Should not raise
    validate(instance=VALID_DEAL_BRIEF, schema=schema)


def test_deal_brief_schema_missing_recommendation_fails():
    schema = _load_schema()
    bad = {k: v for k, v in VALID_DEAL_BRIEF.items() if k != "recommendation"}
    with pytest.raises(ValidationError):
        validate(instance=bad, schema=schema)


def test_deal_brief_schema_missing_findings_fails():
    schema = _load_schema()
    bad = {k: v for k, v in VALID_DEAL_BRIEF.items() if k != "findings"}
    with pytest.raises(ValidationError):
        validate(instance=bad, schema=schema)


def test_deal_brief_schema_missing_payment_validation_fails():
    schema = _load_schema()
    bad = {k: v for k, v in VALID_DEAL_BRIEF.items() if k != "payment_validation"}
    with pytest.raises(ValidationError):
        validate(instance=bad, schema=schema)


def test_deal_brief_schema_finding_invalid_severity_fails():
    schema = _load_schema()
    bad_findings = [
        {
            "id": "D1",
            "area": "clause_deviation",
            "severity": "catastrophic",  # not in enum
            "description": "...",
            "citation": "Cl. 5",
        }
    ]
    bad = {**VALID_DEAL_BRIEF, "findings": bad_findings}
    with pytest.raises(ValidationError):
        validate(instance=bad, schema=schema)


def test_deal_brief_schema_finding_invalid_area_fails():
    schema = _load_schema()
    bad_findings = [
        {
            "id": "D1",
            "area": "wrong_area",  # not in enum
            "severity": "critical",
            "description": "...",
            "citation": "Cl. 5",
        }
    ]
    bad = {**VALID_DEAL_BRIEF, "findings": bad_findings}
    with pytest.raises(ValidationError):
        validate(instance=bad, schema=schema)


def test_deal_brief_schema_payment_validation_missing_errors_field_fails():
    schema = _load_schema()
    bad_pv = {"stated_total_pct": 98, "computed_total_pct": 98}  # missing "errors"
    bad = {**VALID_DEAL_BRIEF, "payment_validation": bad_pv}
    with pytest.raises(ValidationError):
        validate(instance=bad, schema=schema)


# ---------------------------------------------------------------------------
# 3. Regulated control level enforces auto_approve=False server-side
# ---------------------------------------------------------------------------

def test_regulated_control_level_overrides_auto_approve_to_false(tmp_path) -> None:
    """Even if the caller passes auto_approve_human_review=True, the regulated
    control level must override it to False so the gate visibly blocks."""
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
        _use_mock_llm(service)

        result = asyncio.run(
            service.execute_task(
                prompt=SPA_PROMPT,
                deterministic=True,
                determinism_mode=DeterminismMode.best_effort_deterministic,
                control_level=ControlLevel.regulated,
                auto_approve_human_review=True,  # caller asks for auto-approve
                use_sample_data=False,
                files=[],
            )
        )

    # The regulated control level must have suppressed auto-approve,
    # causing the run to pause at the approval gate.
    assert result.status == TaskStatus.paused, (
        f"Expected paused but got {result.status!r}; "
        "regulated control level must override auto_approve_human_review=True"
    )
    assert result.pending_review_node_id is not None


# ---------------------------------------------------------------------------
# 4. SPA program approval gate pauses execution
# ---------------------------------------------------------------------------

def test_spa_program_pauses_at_human_review_gate(tmp_path) -> None:
    """Running the SPA program with auto_approve=False must pause at the
    human_review node and leave deal_brief_synthesis pending."""
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
        _use_mock_llm(service)

        result = asyncio.run(
            service.execute_task(
                prompt=SPA_PROMPT,
                deterministic=True,
                determinism_mode=DeterminismMode.best_effort_deterministic,
                control_level=ControlLevel.regulated,
                auto_approve_human_review=False,
                use_sample_data=False,
                files=[],
            )
        )

    assert result.status == TaskStatus.paused
    assert result.pending_review_node_id is not None

    node_ids = {n.id for n in result.nodes}
    assert "human_review" in node_ids or result.pending_review_node_id is not None, (
        "Expected a human_review gate node in the graph"
    )

    # deal_brief_synthesis must not have completed while the gate is blocked
    synthesis_nodes = [n for n in result.nodes if n.id == "deal_brief_synthesis"]
    if synthesis_nodes:
        assert synthesis_nodes[0].status != "completed", (
            "deal_brief_synthesis must not complete before the human_review gate is cleared"
        )


def test_spa_program_resumes_after_approval(tmp_path) -> None:
    """Approving the paused human_review node should unblock synthesis."""
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
        _use_mock_llm(service)

        run = asyncio.run(
            service.execute_task(
                prompt=SPA_PROMPT,
                deterministic=True,
                determinism_mode=DeterminismMode.best_effort_deterministic,
                control_level=ControlLevel.regulated,
                auto_approve_human_review=False,
                use_sample_data=False,
                files=[],
            )
        )

        assert run.status == TaskStatus.paused
        assert run.pending_review_node_id is not None

        resumed = service.pass_and_verify_node(
            run.task_id,
            run.pending_review_node_id,
            reviewer="sevc-reviewer",
        )

    # After approval, the gate node must be verified
    gate = next((n for n in resumed.nodes if n.id == run.pending_review_node_id), None)
    assert gate is not None
    assert gate.approval_state.approved_count >= gate.approval_state.required_approvals
    assert any(
        r.reviewer == "sevc-reviewer"
        for r in resumed.review_history
        if r.node_id == run.pending_review_node_id
    )


# ---------------------------------------------------------------------------
# 5. Node cache invalidate_by_program
# ---------------------------------------------------------------------------

def _make_minimal_state(program_id: str = "spa_contract_to_cash_v1", version: str = "1.0.0") -> GraphReasoningState:
    return GraphReasoningState(
        task_id="test-task",
        prompt="test prompt",
        template_id=f"{program_id}_template",
        program_id=program_id,
        program_version=version,
        deterministic=True,
        nodes={},
        edges=[],
        source_documents=[],
    )


def _make_minimal_node(node_id: str = "test_node") -> GraphNodeState:
    return GraphNodeState(
        id=node_id,
        title="Test Node",
        subtitle="test",
        operation_type="analyze",
        instruction="do the thing",
        priority=10,
        status="pending",
    )


def _make_result() -> NodeExecutionResult:
    return NodeExecutionResult(output={"result": "ok"}, reasoning_trace="trace", thought_summary="done")


def test_node_cache_invalidate_by_program_deletes_matching_rows(tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'cache_test.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with SessionLocal() as db:
        cache = NodeCacheService(db)
        state = _make_minimal_state()
        node_a = _make_minimal_node("node_a")
        node_b = _make_minimal_node("node_b")

        key_a = cache.build_key(state, node_a)
        key_b = cache.build_key(state, node_b)

        cache.set(key_a, state, node_a, _make_result())
        cache.set(key_b, state, node_b, _make_result())

        assert cache.get(key_a) is not None
        assert cache.get(key_b) is not None

        deleted = cache.invalidate_by_program(state.program_id)

        assert deleted == 2
        assert cache.get(key_a) is None
        assert cache.get(key_b) is None


def test_node_cache_invalidate_only_deletes_target_program(tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'cache_multi_test.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with SessionLocal() as db:
        cache = NodeCacheService(db)

        state_spa = _make_minimal_state("spa_contract_to_cash_v1")
        state_fin = _make_minimal_state("financial_audit_v1")
        node = _make_minimal_node("shared_node")

        key_spa = cache.build_key(state_spa, node)
        key_fin = cache.build_key(state_fin, node)

        cache.set(key_spa, state_spa, node, _make_result())
        cache.set(key_fin, state_fin, node, _make_result())

        deleted = cache.invalidate_by_program("spa_contract_to_cash_v1")

        assert deleted == 1
        assert cache.get(key_spa) is None
        assert cache.get(key_fin) is not None, "financial_audit rows must not be affected"


# ---------------------------------------------------------------------------
# 6. Program version change naturally misses the cache
# ---------------------------------------------------------------------------

def test_cache_key_differs_across_program_versions(tmp_path) -> None:
    """The cache key embeds program_version; bumping the version silently
    misses the cache without any explicit invalidation call."""
    url = f"sqlite:///{tmp_path / 'cache_version_test.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with SessionLocal() as db:
        cache = NodeCacheService(db)
        node = _make_minimal_node()

        state_v1 = _make_minimal_state(version="1.0.0")
        state_v2 = _make_minimal_state(version="2.0.0")

        key_v1 = cache.build_key(state_v1, node)
        key_v2 = cache.build_key(state_v2, node)

        assert key_v1 != key_v2, "Cache keys must differ when program_version changes"

        cache.set(key_v1, state_v1, node, _make_result())

        # v2 should be a cache miss without any explicit invalidation
        assert cache.get(key_v2) is None
        assert cache.get(key_v1) is not None
