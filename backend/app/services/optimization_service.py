from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.models import OptimizationRunRecord
from app.models.api import (
    ExperimentRunRequest,
    OptimizationCandidateResult,
    OptimizationProfileRequest,
    OptimizationRunRequest,
    OptimizationRunResponse,
)
from app.models.artifacts import RegistryArtifact
from app.services.artifact_registry_service import ArtifactRegistryService
from app.services.experiment_service import ExperimentService


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OptimizationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.experiment_service = ExperimentService(db)
        self.artifact_registry = ArtifactRegistryService(db)

    async def run(self, request: OptimizationRunRequest, task_runner) -> OptimizationRunResponse:
        candidate_results: list[OptimizationCandidateResult] = []

        instruction_prefixes = request.instruction_prefixes or [""]
        policies = request.policies or ["priority_based"]
        profiles = request.evaluation_profiles or [OptimizationProfileRequest(name="default", evaluation_ids=[])]

        for prefix in instruction_prefixes:
            for policy in policies:
                for profile in profiles:
                    experiment = await self.experiment_service.run(
                        ExperimentRunRequest(
                            name=f"{request.name}:{policy}:{profile.name or 'default'}",
                            prompts=request.prompts,
                            deterministic=request.deterministic,
                            use_sample_data=request.use_sample_data,
                            auto_approve_human_review=request.auto_approve_human_review,
                        ),
                        lambda **kwargs: task_runner(
                            **kwargs,
                            execution_overrides={
                                "policy": policy,
                                "instruction_prefix": prefix,
                                "additional_evaluation_ids": profile.evaluation_ids,
                            },
                        ),
                    )
                    score = self._score_candidate(experiment.accuracy_score, experiment.runtime_seconds, experiment.tokens_used)
                    candidate_results.append(
                        OptimizationCandidateResult(
                            candidate_id=uuid4().hex[:10],
                            experiment_id=experiment.experiment_id,
                            label=self._candidate_label(policy, prefix, profile),
                            instruction_prefix=prefix,
                            policy=policy,
                            evaluation_ids=profile.evaluation_ids,
                            accuracy_score=experiment.accuracy_score,
                            runtime_seconds=experiment.runtime_seconds,
                            tokens_used=experiment.tokens_used,
                            score=score,
                            task_ids=experiment.task_ids,
                        )
                    )

        candidate_results.sort(key=lambda item: (-item.score, -item.accuracy_score, item.runtime_seconds, item.tokens_used))
        best_candidate = candidate_results[0] if candidate_results else None
        optimization_id = uuid4().hex[:12]
        promoted_artifact_id = None
        promoted_version = None

        if request.promote_best and best_candidate is not None:
            promoted_artifact_id, promoted_version = self._promote_best_candidate(request, best_candidate)

        record = OptimizationRunRecord(
            optimization_id=optimization_id,
            name=request.name,
            status="completed",
            candidate_results=[item.model_dump(mode="json") for item in candidate_results],
            best_candidate=best_candidate.model_dump(mode="json") if best_candidate else None,
            promoted_artifact_id=promoted_artifact_id,
            promoted_version=promoted_version,
            payload={
                "deterministic": request.deterministic,
                "use_sample_data": request.use_sample_data,
                "auto_approve_human_review": request.auto_approve_human_review,
            },
        )
        self.db.add(record)
        self.db.commit()

        return OptimizationRunResponse(
            optimization_id=optimization_id,
            name=request.name,
            status="completed",
            candidate_results=candidate_results,
            best_candidate=best_candidate,
            promoted_artifact_id=promoted_artifact_id,
            promoted_version=promoted_version,
            created_at=record.created_at or utcnow(),
        )

    def list_runs(self) -> list[OptimizationRunResponse]:
        records = (
            self.db.query(OptimizationRunRecord)
            .order_by(OptimizationRunRecord.created_at.desc())
            .limit(50)
            .all()
        )
        return [
            OptimizationRunResponse(
                optimization_id=record.optimization_id,
                name=record.name,
                status=record.status,
                candidate_results=[OptimizationCandidateResult.model_validate(item) for item in record.candidate_results],
                best_candidate=OptimizationCandidateResult.model_validate(record.best_candidate)
                if record.best_candidate
                else None,
                promoted_artifact_id=record.promoted_artifact_id,
                promoted_version=record.promoted_version,
                created_at=record.created_at,
            )
            for record in records
        ]

    @staticmethod
    def _score_candidate(accuracy_score: float, runtime_seconds: float, tokens_used: int) -> float:
        return (accuracy_score * 100.0) - runtime_seconds - (tokens_used / 10000.0)

    @staticmethod
    def _candidate_label(policy: str, prefix: str, profile: OptimizationProfileRequest) -> str:
        prefix_label = prefix.strip()[:20] or "default-prompt"
        profile_label = profile.name or "default-evals"
        return f"{policy}:{profile_label}:{prefix_label}"

    def _promote_best_candidate(
        self,
        request: OptimizationRunRequest,
        best_candidate: OptimizationCandidateResult,
    ) -> tuple[str, str]:
        artifact_id = f"{self._slug(request.name)}_optimized_profile"
        version = self._next_version("template", artifact_id)
        justification = (
            f"Promoted by optimization run because candidate {best_candidate.label} scored {best_candidate.score:.2f} "
            f"with accuracy {best_candidate.accuracy_score:.2f}, runtime {best_candidate.runtime_seconds:.2f}s, "
            f"and {best_candidate.tokens_used} tokens."
        )
        self.artifact_registry.upsert(
            RegistryArtifact(
                kind="template",
                artifact_id=artifact_id,
                version=version,
                name=f"{request.name} Optimized Profile",
                description="Optimizer-selected runtime profile.",
                payload={
                    "template_id": artifact_id,
                    "name": f"{request.name} Optimized Profile",
                    "description": "Optimizer-selected runtime profile.",
                    "policy": best_candidate.policy,
                    "instruction_prefix": best_candidate.instruction_prefix,
                    "evaluation_ids": best_candidate.evaluation_ids,
                    "benchmark_prompts": request.prompts,
                    "selection_metrics": {
                        "accuracy_score": best_candidate.accuracy_score,
                        "runtime_seconds": best_candidate.runtime_seconds,
                        "tokens_used": best_candidate.tokens_used,
                        "score": best_candidate.score,
                    },
                },
                source="optimizer",
                justification=justification,
            )
        )
        promoted = self.artifact_registry.promote("template", artifact_id, version, justification)
        return promoted.artifact_id, promoted.version

    def _next_version(self, kind: str, artifact_id: str) -> str:
        versions = []
        for artifact in self.artifact_registry.list(kind):
            if artifact.artifact_id == artifact_id:
                versions.append(artifact.version)
        if not versions:
            return "1.0.0"
        patch_versions = []
        for version in versions:
            parts = version.split(".")
            if len(parts) == 3 and all(part.isdigit() for part in parts):
                patch_versions.append(tuple(int(part) for part in parts))
        if not patch_versions:
            return "1.0.0"
        major, minor, patch = max(patch_versions)
        return f"{major}.{minor}.{patch + 1}"

    @staticmethod
    def _slug(value: str) -> str:
        return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")[:48] or "optimization"
