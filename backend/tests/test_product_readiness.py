import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import EmbeddingRecord
from app.models.artifacts import RegistryArtifact
from app.models.runtime import ReviewDecision, TaskStatus
from app.services.artifact_registry_service import ArtifactRegistryService
from app.services.llm_gateway import MockProvider
from app.services.optimization_service import OptimizationService
from app.services.task_service import TaskService
from app.models.api import OptimizationProfileRequest, OptimizationRunRequest


def _session_factory(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'product-ready.db'}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _use_mock_llm(service: TaskService) -> None:
    service.llm_gateway.provider = MockProvider()


def test_artifact_registry_supports_versioning_and_promotion(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = ArtifactRegistryService(db)
        evaluations = service.list("evaluations")
        assert any(artifact.artifact_id == "output_present" for artifact in evaluations)

        saved = service.upsert(
            RegistryArtifact(
                kind="policy",
                artifact_id="cost_guarded",
                version="1.0.0",
                name="Cost Guarded",
                description="Cost-aware policy for tests.",
                payload={
                    "policy_id": "cost_guarded",
                    "description": "Select the least expensive ready node first.",
                    "selection_strategy": "cost_aware",
                    "expansion_rules": [],
                    "exploration_limits": {"max_parallel": 1},
                },
            )
        )
        promoted = service.promote("policies", saved.artifact_id, saved.version, "Approved for benchmark use.")
        versions = service.list_versions("policy", saved.artifact_id)
        promotions = service.list_promotions("policy", saved.artifact_id)

        assert promoted.status == "promoted"
        assert service.get("policy", "cost_guarded").version == "1.0.0"
        assert versions[0].artifact_id == "cost_guarded"
        assert promotions[0].justification == "Approved for benchmark use."


def test_task_service_pauses_for_review_and_resumes(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
        _use_mock_llm(service)
        paused = asyncio.run(
            service.execute_task(
                prompt="Perform a financial audit for Invisium FY2026",
                deterministic=True,
                auto_approve_human_review=False,
                use_sample_data=True,
                files=[],
            )
        )

        assert paused.status == TaskStatus.paused
        assert paused.pending_review_node_id is not None
        assert db.query(EmbeddingRecord).count() > 0

        resumed = service.submit_review(
            paused.task_id,
            ReviewDecision(
                node_id=paused.pending_review_node_id or "",
                reviewer="qa-reviewer",
                decision="approved",
                comments="Proceed with synthesis.",
            ),
        )

        assert resumed.status == TaskStatus.completed
        assert resumed.final_output is not None
        assert any(review.decision == "approved" for review in resumed.review_history)


def test_runtime_meets_local_performance_targets(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
        _use_mock_llm(service)
        result = asyncio.run(
            service.execute_task(
                prompt="Perform a financial audit for Invisium FY2026",
                deterministic=True,
                auto_approve_human_review=True,
                use_sample_data=True,
                files=[],
            )
        )

        assert result.status in {TaskStatus.completed, TaskStatus.paused}
        assert (result.graph_build_ms or 0) < 5000
        assert all(metric < 250 for metric in result.scheduler_metrics_ms)


def test_task_service_registers_node_schemas_and_validation_logs(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    with SessionLocal() as db:
        service = TaskService(db)
        _use_mock_llm(service)
        result = asyncio.run(
            service.execute_task(
                prompt="Perform a financial audit for Invisium FY2026",
                deterministic=True,
                auto_approve_human_review=True,
                use_sample_data=True,
                files=[],
            )
        )

        schemas = ArtifactRegistryService(db).list("schema")
        generated_node_schemas = [artifact for artifact in schemas if "_input_v1" in artifact.artifact_id or "_output_v1" in artifact.artifact_id]

        assert result.schema_validation_logs
        assert all(log.passed for log in result.schema_validation_logs)
        assert generated_node_schemas


def test_optimization_service_selects_and_promotes_best_candidate(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)

    async def fake_task_runner(
        prompt: str,
        deterministic: bool,
        auto_approve_human_review: bool,
        use_sample_data: bool,
        files: list,
        determinism_mode=None,
        control_level=None,
        execution_overrides=None,
    ):
        policy = (execution_overrides or {}).get("policy", "priority_based")
        completed = policy == "cost_aware"
        token_count = 500 if completed else 5000
        return type(
            "FakeResult",
            (),
            {
                "task_id": f"{policy}_{prompt[:4]}",
                "status": TaskStatus.completed if completed else TaskStatus.failed,
                "audit_package": {"grs": {"budget_usage": {"tokens_used": token_count}}},
            },
        )()

    with SessionLocal() as db:
        service = OptimizationService(db)
        response = asyncio.run(
            service.run(
                OptimizationRunRequest(
                    name="Policy Tuning",
                    prompts=["Prompt A", "Prompt B"],
                    instruction_prefixes=["Focus on concision."],
                    policies=["priority_based", "cost_aware"],
                    evaluation_profiles=[OptimizationProfileRequest(name="default", evaluation_ids=["output_present"])],
                    deterministic=True,
                    promote_best=True,
                ),
                fake_task_runner,
            )
        )

        promoted = ArtifactRegistryService(db).get("template", "policy_tuning_optimized_profile")

        assert response.best_candidate is not None
        assert response.best_candidate.policy == "cost_aware"
        assert response.promoted_artifact_id == "policy_tuning_optimized_profile"
        assert promoted.status == "promoted"
