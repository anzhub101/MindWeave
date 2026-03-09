from app.models.artifacts import BudgetSpec
from app.models.runtime import (
    ClaimClassification,
    EvidenceReference,
    EvidenceSupportLevel,
    FindingRecord,
    GraphEdge,
    GraphNodeState,
    GraphReasoningState,
    NodeExecutionResult,
    NodeStatus,
    ThoughtRecord,
    TaskStatus,
    VerificationStatus,
)
from app.runtime.audit import AuditStore
from app.runtime.budget import BudgetManager
from app.runtime.constraints import ConstraintInjector
from app.runtime.controller import Controller
from app.runtime.scheduler import Scheduler
from app.services.document_processor import DocumentProcessor
from app.services.generic_reasoning_operator import GenericReasoningOperator
from app.services.knowledge_base import KnowledgeBase
from app.services.llm_gateway import LLMGateway
from app.services.program_synthesizer import ProgramSynthesisService
from app.services.task_service import TaskService


def test_verify_gate_blocks_guarded_node() -> None:
    budget = BudgetSpec(max_nodes=4, max_tokens=100, max_runtime_seconds=30)
    state = GraphReasoningState(
        task_id="guard-test",
        prompt="Perform a financial audit for Invisium FY2026",
        template_id="financial_audit_v1",
        program_id="financial_audit_v1",
        program_version="1.0.0",
        deterministic=True,
        budget_spec=budget,
        nodes={
            "verify_gate": GraphNodeState(
                id="verify_gate",
                title="Verify Gate",
                subtitle="Verify prerequisites",
                operation_type="verify",
                priority=10,
                verification_status=VerificationStatus.pending,
            ),
            "guarded": GraphNodeState(
                id="guarded",
                title="Guarded Node",
                subtitle="Downstream operation",
                operation_type="aggregate",
                priority=20,
                depends_on=["verify_gate"],
                guarded_by=["verify_gate"],
            ),
        },
        edges=[GraphEdge(source="verify_gate", target="guarded")],
    )

    scheduler = Scheduler(ConstraintInjector())
    assert [node.id for node in scheduler.ready_nodes(state)] == ["verify_gate"]

    state.nodes["verify_gate"].status = NodeStatus.completed
    state.nodes["verify_gate"].verification_status = VerificationStatus.failed
    assert scheduler.ready_nodes(state) == []

    state.nodes["verify_gate"].verification_status = VerificationStatus.passed
    assert [node.id for node in scheduler.ready_nodes(state)] == ["guarded"]


def test_synthesized_program_flow_produces_report(tmp_path) -> None:
    llm_gateway = LLMGateway()
    synthesizer = ProgramSynthesisService(llm_gateway)
    synthesizer.generated_root = tmp_path / "generated_artifacts"
    bundle = synthesizer.synthesize("Perform a financial audit for Invisium FY2026")
    program = bundle.program
    processor = DocumentProcessor()
    processor.storage_root = tmp_path
    documents = processor.load_sample_pack("pytest-run")

    nodes = {
        node.id: GraphNodeState(
            id=node.id,
            title=node.title,
            subtitle=node.subtitle,
            operation_type=node.operation_type,
            instruction=node.instruction,
            success_criteria=node.success_criteria,
            priority=node.priority,
            depends_on=node.depends_on,
            guarded_by=node.guarded_by,
            next_nodes=node.next_nodes,
            metadata=node.metadata,
        )
        for node in program.nodes
    }
    edges = [GraphEdge(source=node.id, target=target_id) for node in program.nodes for target_id in node.next_nodes]
    state = GraphReasoningState(
        task_id="pytest-run",
        prompt="Perform a financial audit for Invisium FY2026",
        template_id=bundle.template_id,
        program_id=program.program_id,
        program_version=program.version,
        domain=program.domain,
        deterministic=True,
        requirements_reference_path=bundle.source_requirements_path,
        source_documents=documents,
        nodes=nodes,
        edges=edges,
        budget_spec=program.budget,
        program_blueprint=program.model_dump(mode="json", by_alias=True),
        output_schema_definition=bundle.output_schema_definition,
    )

    controller = Controller(
        scheduler=Scheduler(ConstraintInjector()),
        constraints=ConstraintInjector(),
        budget_manager=BudgetManager(),
        audit_store=AuditStore(tmp_path),
        operation_runner=GenericReasoningOperator(KnowledgeBase(documents), llm_gateway),
    )

    completed = controller.run(state)
    assert completed.status == TaskStatus.completed
    assert completed.final_output is not None
    assert "conclusion" in completed.final_output or "objective" in completed.final_output
    assert any(log.status in {VerificationStatus.passed, VerificationStatus.skipped} for log in completed.verification_logs)


def test_delegated_child_nodes_gate_downstream_execution_and_audit_completion(tmp_path) -> None:
    budget = BudgetSpec(max_nodes=8, max_tokens=1000, max_runtime_seconds=30)
    state = GraphReasoningState(
        task_id="delegation-test",
        prompt="Expand the fraud branch and summarize back into the final report.",
        template_id="delegation_template",
        program_id="delegation_program",
        program_version="1.0.0",
        deterministic=True,
        budget_spec=budget,
        program_blueprint={"policy": "priority_based", "convergence_rule": "no_pending_nodes"},
        nodes={
            "fraud_branch": GraphNodeState(
                id="fraud_branch",
                title="Fraud Branch",
                subtitle="Parent branch",
                operation_type="analyze",
                priority=10,
                executor_type="agent_operator",
                max_child_agents=1,
                max_recursion_depth=1,
                child_token_budget=512,
                delegated_summary_required=True,
                next_nodes=["final_report"],
                metadata={"complexity_score": 10},
            ),
            "final_report": GraphNodeState(
                id="final_report",
                title="Final Report",
                subtitle="Synthesize delegated output",
                operation_type="synthesize",
                priority=30,
                depends_on=["fraud_branch"],
                next_nodes=[],
            ),
        },
        edges=[GraphEdge(source="fraud_branch", target="final_report")],
    )

    evidence = EvidenceReference(
        id="evidence_fraud_chunk",
        document_id="doc_fraud",
        document_name="fraud_findings.txt",
        chunk_id="doc_fraud_chunk_1",
        retrieval_score=0.97,
        support_level=EvidenceSupportLevel.direct,
        citation_mode="direct",
        source_type="retrieved",
        text_excerpt="Vendor payment exception with matching control evidence.",
    )

    class DelegatingRunner:
        def execute(self, current_state: GraphReasoningState, node: GraphNodeState) -> NodeExecutionResult:
            if node.id == "fraud_branch":
                return NodeExecutionResult(
                    output={"branch": "fraud"},
                    evidence_refs=[evidence],
                    verification_status=VerificationStatus.skipped,
                    thought_summary="Fraud branch queued for delegated review.",
                    llm_usage_tokens=10,
                    finding_records=[
                        FindingRecord(
                            id="fraud_branch_finding_1",
                            text="Fraud branch requires delegated review.",
                            support_level=EvidenceSupportLevel.direct,
                            claim_classification=ClaimClassification.grounded,
                            evidence_refs=[evidence],
                        )
                    ],
                    spawned_nodes=[
                        GraphNodeState(
                            id="fraud_branch_child_1",
                            title="Fraud Branch Child",
                            subtitle="Delegated child analysis",
                            operation_type="analyze",
                            priority=20,
                            depends_on=["fraud_branch"],
                            next_nodes=["final_report"],
                            spawned_from="fraud_branch",
                            delegated_summary_required=True,
                        )
                    ],
                )
            if node.id == "fraud_branch_child_1":
                return NodeExecutionResult(
                    output={"delegated_summary": "Child branch confirmed the payment exception."},
                    evidence_refs=[evidence],
                    verification_status=VerificationStatus.skipped,
                    thought_summary="Delegated child confirmed the payment exception.",
                    llm_usage_tokens=8,
                    finding_records=[
                        FindingRecord(
                            id="fraud_child_finding_1",
                            text="Delegated child confirmed the payment exception.",
                            support_level=EvidenceSupportLevel.direct,
                            claim_classification=ClaimClassification.grounded,
                            evidence_refs=[evidence],
                        )
                    ],
                )
            return NodeExecutionResult(
                output={"conclusion": "Final report includes delegated branch analysis."},
                evidence_refs=[evidence],
                verification_status=VerificationStatus.skipped,
                thought_summary="Final synthesis completed.",
                llm_usage_tokens=5,
                finding_records=[
                    FindingRecord(
                        id="final_finding_1",
                        text="Final report includes the delegated fraud branch.",
                        support_level=EvidenceSupportLevel.direct,
                        claim_classification=ClaimClassification.grounded,
                        evidence_refs=[evidence],
                    )
                ],
                final_output={
                    "objective": "Fraud branch review",
                    "conclusion": "Delegated branch completed before final synthesis.",
                    "findings": ["Delegated fraud branch completed."],
                    "finding_records": [
                        {
                            "id": "final_finding_1",
                            "text": "Delegated fraud branch completed.",
                            "support_level": "direct",
                            "claim_classification": "grounded",
                            "evidence_refs": [evidence.model_dump(mode="json")],
                        }
                    ],
                    "evidence_sources": ["doc_fraud"],
                    "next_steps": ["Human review the delegated branch."],
                },
            )

    controller = Controller(
        scheduler=Scheduler(ConstraintInjector()),
        constraints=ConstraintInjector(),
        budget_manager=BudgetManager(),
        audit_store=AuditStore(tmp_path),
        operation_runner=DelegatingRunner(),
    )

    completed = controller.run(state)

    assert completed.status == TaskStatus.completed
    assert completed.execution_sequence == ["fraud_branch", "fraud_branch_child_1", "final_report"]
    assert "fraud_branch_child_1" in completed.nodes["final_report"].depends_on
    assert completed.nodes["fraud_branch"].metadata["delegation_summary_complete"] is True
    assert completed.nodes["fraud_branch"].metadata["delegated_summaries"][0]["child_node_id"] == "fraud_branch_child_1"
    events = [entry.event for entry in completed.logs]
    assert "delegation_spawned" in events
    assert "delegation_child_summary_recorded" in events
    assert "delegation_completed" in events


def test_synthesizer_normalizes_loose_node_schema() -> None:
    synthesizer = ProgramSynthesisService(LLMGateway())
    bundle = synthesizer._normalize_bundle(
        {
            "template_id": "sample_template",
            "template_name": "Sample Template",
            "domain": "general reasoning",
            "mapping_explanation": "Test payload",
            "program": {
                "program_id": "sample_v1",
                "version": "1.0.0",
                "template_id": "sample_template",
                "domain": "general reasoning",
                "goal": "Sample goal",
                "policy": "priority_based",
                "budget": {"max_nodes": 8, "max_tokens": 8000, "max_runtime_seconds": 120},
                "convergence_rule": "no_pending_nodes",
                "output_schema": "sample_schema_v1",
                "nodes": [
                    {
                        "id": "doc intake",
                        "name": "Doc Intake",
                        "type": "generate",
                        "description": "Collect the source material.",
                        "success_criteria": "Documents indexed; no ingestion errors.",
                        "next": ["verification stage"],
                    },
                    {
                        "id": "verification stage",
                        "name": "Verification Stage",
                        "operation": "verify",
                        "description": "Check the collected material.",
                        "success_criteria": {"primary": "Checks passed."},
                        "depends_on": ["doc intake"],
                    },
                ],
            },
            "output_schema_definition": {
                "title": "sample_schema_v1",
                "type": "object",
                "properties": {"result": {"type": "string"}},
            },
        },
        "Sample goal",
    )

    first_node = bundle.program.nodes[0]
    second_node = bundle.program.nodes[1]

    assert first_node.id == "doc_intake"
    assert first_node.title == "Doc Intake"
    assert first_node.operation_type == "generate"
    assert first_node.success_criteria == ["Documents indexed", "no ingestion errors."]
    assert first_node.next_nodes == ["verification_stage"]
    assert second_node.operation_type == "verify"
    assert second_node.depends_on == ["doc_intake"]


def test_synthesizer_accepts_program_only_payload() -> None:
    synthesizer = ProgramSynthesisService(LLMGateway())
    bundle = synthesizer._normalize_bundle(
        {
            "program_id": "program_only_v1",
            "version": "1.0.0",
            "template_id": "program_only_template",
            "domain": "general reasoning",
            "goal": "Program only payload",
            "policy": "priority_based",
            "budget": {"max_nodes": 6, "max_tokens": 6000, "max_runtime_seconds": 120},
            "convergence_rule": "no_pending_nodes",
            "nodes": [
                {
                    "id": "scope",
                    "title": "Scope",
                    "operation_type": "generate",
                    "success_criteria": ["Scope defined"],
                    "next": ["verify_scope"],
                },
                {
                    "id": "verify_scope",
                    "title": "Verify Scope",
                    "operation_type": "verify",
                    "depends_on": ["scope"],
                    "success_criteria": ["Scope verified"],
                },
            ],
        },
        "Program only payload",
    )

    assert bundle.program.program_id == "program_only_v1"
    assert bundle.output_schema_definition["title"] == "program_only_v1_output_schema_v1"
    assert bundle.program.nodes[-1].operation_type == "synthesize"


def test_final_output_normalization_replaces_placeholders() -> None:
    state = GraphReasoningState(
        task_id="normalize-output",
        prompt="Perform a financial audit for Invisium FY2026",
        template_id="generated",
        program_id="generated_v1",
        program_version="1.0.0",
        deterministic=True,
        budget_spec=BudgetSpec(max_nodes=4, max_tokens=4000, max_runtime_seconds=60),
        final_output={
            "objective": "...",
            "conclusion": "...",
            "findings": [None],
            "evidence_sources": [None],
            "next_steps": [None],
        },
    )
    state.thoughts["thought_1"] = ThoughtRecord(
        id="thought_1",
        node_id="node_1",
        summary="Mapped core evidence.",
        content={},
    )

    normalized = TaskService._normalize_final_output(state)

    assert normalized["objective"] == state.prompt
    assert "Human review" in normalized["conclusion"]
    assert normalized["findings"] == ["Mapped core evidence."]
    assert normalized["evidence_sources"] == ["no_evidence_supplied"]
    assert normalized["next_steps"] == [
        "Review the audit package.",
        "Confirm the final conclusion with a human reviewer.",
    ]
