from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.api import (
    ApplyPlannedChangeRequest,
    ArtifactPayloadRequest,
    ArtifactPayloadResponse,
    ArtifactPromotionResponse,
    ArtifactSummary,
    GraphPatchRequest,
    ExperimentRunRequest,
    ExperimentRunResponse,
    OptimizationRunRequest,
    OptimizationRunResponse,
    PlanChangeRequest,
    PlanChangeResponse,
    PromotionRequest,
    ReasoningTraceResponse,
    ReplayTaskRequest,
    RunDiffRequest,
    RunDiffResponse,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    TaskRunListItem,
    TaskRunResponse,
    TemplateSummary,
)
from app.models.artifacts import RegistryArtifact
from app.models.runtime import ControlLevel, DeterminismMode, ReasoningVisibilityTier, ReviewDecision
from app.services.artifact_registry_service import ArtifactRegistryService
from app.services.experiment_service import ExperimentService
from app.services.optimization_service import OptimizationService
from app.services.task_service import TaskService


router = APIRouter()


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/templates", response_model=list[TemplateSummary])
def list_templates(db: Session = Depends(get_db)) -> list[TemplateSummary]:
    return TaskService(db).list_templates()


@router.get("/design/{kind}", response_model=list[ArtifactSummary])
def list_artifacts(kind: str, db: Session = Depends(get_db)) -> list[ArtifactSummary]:
    service = ArtifactRegistryService(db)
    try:
        return [
            ArtifactSummary(
                kind=artifact.kind,
                artifact_id=artifact.artifact_id,
                version=artifact.version,
                name=artifact.name,
                description=artifact.description,
                status=artifact.status,
                source=artifact.source,
                updated_at=artifact.updated_at,
            )
            for artifact in service.list(kind)
        ]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/design/{kind}/{artifact_id}", response_model=ArtifactPayloadResponse)
def get_artifact(
    kind: str,
    artifact_id: str,
    version: str | None = None,
    db: Session = Depends(get_db),
) -> ArtifactPayloadResponse:
    service = ArtifactRegistryService(db)
    try:
        artifact = service.get(kind, artifact_id, version=version)
        return ArtifactPayloadResponse(
            kind=artifact.kind,
            artifact_id=artifact.artifact_id,
            version=artifact.version,
            name=artifact.name,
            description=artifact.description,
            payload=artifact.payload,
            status=artifact.status,
            source=artifact.source,
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
            justification=artifact.justification,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/design/{kind}/{artifact_id}/versions", response_model=list[ArtifactSummary])
def list_artifact_versions(
    kind: str,
    artifact_id: str,
    db: Session = Depends(get_db),
) -> list[ArtifactSummary]:
    service = ArtifactRegistryService(db)
    try:
        return [
            ArtifactSummary(
                kind=artifact.kind,
                artifact_id=artifact.artifact_id,
                version=artifact.version,
                name=artifact.name,
                description=artifact.description,
                status=artifact.status,
                source=artifact.source,
                updated_at=artifact.updated_at,
            )
            for artifact in service.list_versions(kind, artifact_id)
        ]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/design/{kind}/{artifact_id}/promotions", response_model=list[ArtifactPromotionResponse])
def list_artifact_promotions(
    kind: str,
    artifact_id: str,
    db: Session = Depends(get_db),
) -> list[ArtifactPromotionResponse]:
    service = ArtifactRegistryService(db)
    try:
        return [
            ArtifactPromotionResponse(
                kind=promotion.kind,
                artifact_id=promotion.artifact_id,
                version=promotion.version,
                justification=promotion.justification,
                promoted_at=promotion.promoted_at,
            )
            for promotion in service.list_promotions(kind, artifact_id)
        ]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/design/{kind}", response_model=ArtifactPayloadResponse)
def save_artifact(
    kind: str,
    request: ArtifactPayloadRequest,
    db: Session = Depends(get_db),
) -> ArtifactPayloadResponse:
    artifact = ArtifactRegistryService(db).upsert(
        RegistryArtifact(
            kind=kind,
            artifact_id=request.artifact_id,
            version=request.version,
            name=request.name,
            description=request.description,
            payload=request.payload,
            status=request.status,
            source=request.source,
            justification=request.justification,
        )
    )
    return ArtifactPayloadResponse(
        kind=artifact.kind,
        artifact_id=artifact.artifact_id,
        version=artifact.version,
        name=artifact.name,
        description=artifact.description,
        payload=artifact.payload,
        status=artifact.status,
        source=artifact.source,
        created_at=artifact.created_at,
        updated_at=artifact.updated_at,
        justification=artifact.justification,
    )


@router.post("/design/{kind}/{artifact_id}/promote", response_model=ArtifactPayloadResponse)
def promote_artifact(
    kind: str,
    artifact_id: str,
    request: PromotionRequest,
    db: Session = Depends(get_db),
) -> ArtifactPayloadResponse:
    try:
        artifact = ArtifactRegistryService(db).promote(kind, artifact_id, request.version, request.justification)
        return ArtifactPayloadResponse(
            kind=artifact.kind,
            artifact_id=artifact.artifact_id,
            version=artifact.version,
            name=artifact.name,
            description=artifact.description,
            payload=artifact.payload,
            status=artifact.status,
            source=artifact.source,
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
            justification=artifact.justification,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tasks", response_model=list[TaskRunListItem])
def list_tasks(db: Session = Depends(get_db)) -> list[TaskRunListItem]:
    return TaskService(db).list_tasks()


@router.get("/tasks/{task_id}", response_model=TaskRunResponse)
def get_task(task_id: str, db: Session = Depends(get_db)) -> TaskRunResponse:
    try:
        return TaskService(db).get_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/audit")
def get_audit_package(task_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        return TaskService(db).get_audit_package(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/reviews", response_model=list[ReviewDecisionResponse])
def list_reviews(task_id: str, db: Session = Depends(get_db)) -> list[ReviewDecisionResponse]:
    reviews = TaskService(db).list_reviews(task_id)
    return [
        ReviewDecisionResponse(
            task_id=task_id,
            timestamp=review.timestamp,
            node_id=review.node_id,
            reviewer=review.reviewer,
            decision=review.decision,
            comments=review.comments,
        )
        for review in reviews
    ]


@router.post("/tasks/{task_id}/review", response_model=TaskRunResponse)
def submit_review(
    task_id: str,
    request: ReviewDecisionRequest,
    db: Session = Depends(get_db),
) -> TaskRunResponse:
    decision = ReviewDecision(
        node_id=request.node_id,
        reviewer=request.reviewer,
        decision=request.decision,
        comments=request.comments,
    )
    try:
        return TaskService(db).submit_review(task_id, decision)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tasks/execute", response_model=TaskRunResponse)
async def execute_task(
    prompt: str = Form(...),
    deterministic: bool = Form(True),
    determinism_mode: DeterminismMode | None = Form(default=None),
    control_level: ControlLevel = Form(default=ControlLevel.operational),
    auto_approve_human_review: bool = Form(True),
    use_sample_data: bool = Form(True),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
) -> TaskRunResponse:
    service = TaskService(db)
    return await service.execute_task(
        prompt=prompt,
        deterministic=deterministic,
        auto_approve_human_review=auto_approve_human_review,
        use_sample_data=use_sample_data,
        files=files,
        determinism_mode=determinism_mode,
        control_level=control_level,
    )


@router.post("/tasks/{task_id}/replay", response_model=TaskRunResponse)
def replay_task(
    task_id: str,
    request: ReplayTaskRequest,
    db: Session = Depends(get_db),
) -> TaskRunResponse:
    try:
        return TaskService(db).replay_task(
            task_id=task_id,
            snapshot_label=request.snapshot_label,
            resume_from_snapshot=request.resume_from_snapshot,
            auto_approve_human_review=request.auto_approve_human_review,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/patch", response_model=TaskRunResponse)
def patch_task(
    task_id: str,
    request: GraphPatchRequest,
    db: Session = Depends(get_db),
) -> TaskRunResponse:
    try:
        return TaskService(db).apply_graph_patch(
            task_id=task_id,
            patch_type=request.patch_type,
            target_node_id=request.target_node_id,
            change_reason=request.change_reason,
            requested_by=request.requested_by,
            approved_by=request.approved_by,
            payload=request.payload,
            auto_rerun=request.auto_rerun,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/plan-change", response_model=PlanChangeResponse)
def plan_change(
    task_id: str,
    request: PlanChangeRequest,
    db: Session = Depends(get_db),
) -> PlanChangeResponse:
    try:
        return TaskService(db).plan_change(
            task_id=task_id,
            request_text=request.request_text,
            requested_by=request.requested_by,
            selected_node_id=request.selected_node_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/apply-planned-change", response_model=TaskRunResponse)
def apply_planned_change(
    task_id: str,
    request: ApplyPlannedChangeRequest,
    db: Session = Depends(get_db),
) -> TaskRunResponse:
    try:
        return TaskService(db).apply_planned_change(
            task_id=task_id,
            proposal_id=request.proposal_id,
            approved_by=request.approved_by,
            approval_notes=request.approval_notes,
            auto_rerun=request.auto_rerun,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/diff", response_model=RunDiffResponse)
def diff_runs(
    request: RunDiffRequest,
    db: Session = Depends(get_db),
) -> RunDiffResponse:
    try:
        return TaskService(db).diff_runs(request.left_task_id, request.right_task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/trace", response_model=ReasoningTraceResponse)
def get_trace(
    task_id: str,
    tier: ReasoningVisibilityTier = ReasoningVisibilityTier.summary_trace,
    db: Session = Depends(get_db),
) -> ReasoningTraceResponse:
    try:
        return TaskService(db).get_reasoning_trace(task_id, tier)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/experiments", response_model=list[ExperimentRunResponse])
def list_experiments(db: Session = Depends(get_db)) -> list[ExperimentRunResponse]:
    return ExperimentService(db).list_runs()


@router.post("/experiments", response_model=ExperimentRunResponse)
async def run_experiment(
    request: ExperimentRunRequest,
    db: Session = Depends(get_db),
) -> ExperimentRunResponse:
    task_service = TaskService(db)
    return await ExperimentService(db).run(request, task_service.execute_task)


@router.get("/optimizations", response_model=list[OptimizationRunResponse])
def list_optimizations(db: Session = Depends(get_db)) -> list[OptimizationRunResponse]:
    return OptimizationService(db).list_runs()


@router.post("/optimizations", response_model=OptimizationRunResponse)
async def run_optimization(
    request: OptimizationRunRequest,
    db: Session = Depends(get_db),
) -> OptimizationRunResponse:
    task_service = TaskService(db)
    return await OptimizationService(db).run(request, task_service.execute_task)
