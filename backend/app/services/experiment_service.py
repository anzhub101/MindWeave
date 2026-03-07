from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.models import ExperimentRunRecord
from app.models.api import ExperimentRunRequest, ExperimentRunResponse


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExperimentService:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def run(self, request: ExperimentRunRequest, task_runner) -> ExperimentRunResponse:
        started = time.perf_counter()
        task_ids: list[str] = []
        tokens_used = 0
        completed_runs = 0

        for prompt in request.prompts:
            result = await task_runner(
                prompt=prompt,
                deterministic=request.deterministic,
                auto_approve_human_review=request.auto_approve_human_review,
                use_sample_data=request.use_sample_data,
                files=[],
            )
            task_ids.append(result.task_id)
            if result.status.value == "completed":
                completed_runs += 1
            audit_package = result.audit_package or {}
            grs = audit_package.get("grs", {})
            budget_usage = grs.get("budget_usage", {}) if isinstance(grs, dict) else {}
            tokens_used += int(budget_usage.get("tokens_used", 0))

        runtime_seconds = time.perf_counter() - started
        experiment_id = uuid4().hex[:12]
        accuracy_score = completed_runs / max(len(request.prompts), 1)

        record = ExperimentRunRecord(
            experiment_id=experiment_id,
            name=request.name,
            status="completed",
            prompts=request.prompts,
            task_ids=task_ids,
            accuracy_score=accuracy_score,
            runtime_seconds=runtime_seconds,
            tokens_used=tokens_used,
            payload={
                "deterministic": request.deterministic,
                "use_sample_data": request.use_sample_data,
            },
        )
        self.db.add(record)
        self.db.commit()

        return ExperimentRunResponse(
            experiment_id=experiment_id,
            name=request.name,
            status="completed",
            prompts=request.prompts,
            task_ids=task_ids,
            accuracy_score=accuracy_score,
            runtime_seconds=runtime_seconds,
            tokens_used=tokens_used,
            created_at=record.created_at if record.created_at else utcnow(),
        )

    def list_runs(self) -> list[ExperimentRunResponse]:
        records = (
            self.db.query(ExperimentRunRecord)
            .order_by(ExperimentRunRecord.created_at.desc())
            .limit(50)
            .all()
        )
        return [
            ExperimentRunResponse(
                experiment_id=record.experiment_id,
                name=record.name,
                status=record.status,
                prompts=record.prompts,
                task_ids=record.task_ids,
                accuracy_score=record.accuracy_score,
                runtime_seconds=record.runtime_seconds,
                tokens_used=record.tokens_used,
                created_at=record.created_at,
            )
            for record in records
        ]
