from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskRunRecord(Base):
    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prompt: Mapped[str] = mapped_column(Text)
    template_id: Mapped[str] = mapped_column(String(128), index=True)
    program_id: Mapped[str] = mapped_column(String(128), index=True)
    program_version: Mapped[str] = mapped_column(String(32))
    domain: Mapped[str] = mapped_column(String(128), default="general")
    status: Mapped[str] = mapped_column(String(32), index=True)
    deterministic: Mapped[bool] = mapped_column(Boolean, default=True)
    source_documents: Mapped[list] = mapped_column(JSON, default=list)
    final_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    grs_snapshot: Mapped[dict] = mapped_column(JSON)
    audit_package: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class ArtifactRecord(Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("kind", "artifact_id", "version", name="uq_artifact_kind_id_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    artifact_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    source: Mapped[str] = mapped_column(String(32), default="user")
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PromotionRecord(Base):
    __tablename__ = "promotion_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    artifact_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[str] = mapped_column(String(32))
    justification: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NodeCacheRecord(Base):
    __tablename__ = "node_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    program_id: Mapped[str] = mapped_column(String(128), index=True)
    node_id: Mapped[str] = mapped_column(String(128), index=True)
    deterministic: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewDecisionRecord(Base):
    __tablename__ = "review_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    node_id: Mapped[str] = mapped_column(String(128), index=True)
    reviewer: Mapped[str] = mapped_column(String(128))
    decision: Mapped[str] = mapped_column(String(32), index=True)
    comments: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExperimentRunRecord(Base):
    __tablename__ = "experiment_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), index=True)
    prompts: Mapped[list] = mapped_column(JSON, default=list)
    task_ids: Mapped[list] = mapped_column(JSON, default=list)
    accuracy_score: Mapped[float] = mapped_column(Float, default=0.0)
    runtime_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OptimizationRunRecord(Base):
    __tablename__ = "optimization_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    optimization_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), index=True)
    candidate_results: Mapped[list] = mapped_column(JSON, default=list)
    best_candidate: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    promoted_artifact_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    promoted_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmbeddingRecord(Base):
    __tablename__ = "embeddings"
    __table_args__ = (UniqueConstraint("task_id", "chunk_id", name="uq_embedding_task_chunk"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str] = mapped_column(String(128), index=True)
    chunk_id: Mapped[str] = mapped_column(String(128), index=True)
    vector: Mapped[list] = mapped_column(JSON, default=list)
    text_excerpt: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
