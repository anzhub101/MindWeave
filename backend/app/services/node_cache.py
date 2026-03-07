from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import NodeCacheRecord
from app.models.runtime import GraphNodeState, GraphReasoningState, NodeExecutionResult


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NodeCacheService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def build_key(self, state: GraphReasoningState, node: GraphNodeState) -> str:
        payload = {
            "program_id": state.program_id,
            "program_version": state.program_version,
            "node_id": node.id,
            "prompt": state.prompt,
            "deterministic": state.deterministic,
            "inputs": node.inputs,
            "instruction": node.instruction,
            "output_schema_definition": state.output_schema_definition if node.operation_type == "synthesize" else None,
        }
        serialized = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def get(self, cache_key: str) -> NodeExecutionResult | None:
        record = self.db.query(NodeCacheRecord).filter(NodeCacheRecord.cache_key == cache_key).one_or_none()
        if record is None:
            return None
        record.last_used_at = utcnow()
        self.db.commit()
        return NodeExecutionResult.model_validate(record.payload)

    def set(
        self,
        cache_key: str,
        state: GraphReasoningState,
        node: GraphNodeState,
        result: NodeExecutionResult,
    ) -> None:
        payload = result.model_dump(mode="json")
        existing = self.db.query(NodeCacheRecord).filter(NodeCacheRecord.cache_key == cache_key).one_or_none()
        if existing is None:
            existing = NodeCacheRecord(
                cache_key=cache_key,
                program_id=state.program_id,
                node_id=node.id,
                deterministic=state.deterministic,
                payload=payload,
            )
            self.db.add(existing)
        else:
            existing.payload = payload
            existing.last_used_at = utcnow()
        self.db.commit()
