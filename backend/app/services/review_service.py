from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import ReviewDecisionRecord
from app.models.runtime import ReviewDecision


class ReviewService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_task(self, task_id: str) -> list[ReviewDecision]:
        records = (
            self.db.query(ReviewDecisionRecord)
            .filter(ReviewDecisionRecord.task_id == task_id)
            .order_by(ReviewDecisionRecord.created_at.asc())
            .all()
        )
        return [
            ReviewDecision(
                timestamp=record.created_at,
                node_id=record.node_id,
                reviewer=record.reviewer,
                decision=record.decision,
                comments=record.comments,
            )
            for record in records
        ]

    def record(self, task_id: str, decision: ReviewDecision) -> ReviewDecision:
        self.db.add(
            ReviewDecisionRecord(
                task_id=task_id,
                node_id=decision.node_id,
                reviewer=decision.reviewer,
                decision=decision.decision,
                comments=decision.comments,
                created_at=decision.timestamp,
            )
        )
        self.db.commit()
        return decision
