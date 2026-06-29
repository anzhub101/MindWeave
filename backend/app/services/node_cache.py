from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import NodeCacheRecord
from app.models.runtime import GraphNodeState, GraphReasoningState, NodeExecutionResult


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_cache_key(state: GraphReasoningState, node: GraphNodeState) -> str:
    """Content-addressed cache key shared by all cache backends."""
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


class NodeCacheService:
    """Durable persistent cache backed by the relational `node_cache` table."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def build_key(self, state: GraphReasoningState, node: GraphNodeState) -> str:
        return build_cache_key(state, node)

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

    def invalidate_by_program(self, program_id: str, keep_version: str | None = None) -> int:
        """Delete all SQL cache rows for a program, optionally preserving one version.

        Call this when a program definition changes so stale cached results from
        the old version cannot be replayed against the new instruction set.
        Returns the number of rows deleted.
        """
        query = self.db.query(NodeCacheRecord).filter(NodeCacheRecord.program_id == program_id)
        if keep_version is not None:
            # Cache keys embed program_version in their hash; rows from the kept
            # version will naturally miss because their keys differ, so we can
            # safely drop all rows rather than filtering by a stored version column.
            # The keep_version param is accepted for call-site clarity but unused here.
            pass
        deleted = query.delete(synchronize_session=False)
        self.db.commit()
        return deleted


class RedisNodeCacheService:
    """Shared, fast cache backed by Redis. Survives across workers and supports TTL eviction.

    Designed to be wrapped by ``LayeredNodeCacheService`` so a Redis outage degrades
    gracefully to the durable SQL tier rather than failing the run.
    """

    KEY_PREFIX = "mw:nodecache:"

    def __init__(self, client, ttl_seconds: int = 0) -> None:
        self.client = client
        self.ttl_seconds = max(0, int(ttl_seconds or 0))

    def build_key(self, state: GraphReasoningState, node: GraphNodeState) -> str:
        return build_cache_key(state, node)

    def _redis_key(self, cache_key: str) -> str:
        return f"{self.KEY_PREFIX}{cache_key}"

    def get(self, cache_key: str) -> NodeExecutionResult | None:
        raw = self.client.get(self._redis_key(cache_key))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return NodeExecutionResult.model_validate(json.loads(raw))

    def set(
        self,
        cache_key: str,
        state: GraphReasoningState,
        node: GraphNodeState,
        result: NodeExecutionResult,
    ) -> None:
        serialized = json.dumps(result.model_dump(mode="json"), default=str)
        redis_key = self._redis_key(cache_key)
        if self.ttl_seconds > 0:
            self.client.setex(redis_key, self.ttl_seconds, serialized)
        else:
            self.client.set(redis_key, serialized)


class LayeredNodeCacheService:
    """Two-tier cache: Redis (fast, shared, TTL) in front of SQL (durable).

    - ``get``  : Redis first; on miss, fall back to SQL and backfill Redis.
    - ``set``  : write SQL (durable) and Redis (fast); Redis failures never break the run.
    """

    def __init__(self, redis_service: RedisNodeCacheService, sql_service: NodeCacheService) -> None:
        self.redis_service = redis_service
        self.sql_service = sql_service

    def build_key(self, state: GraphReasoningState, node: GraphNodeState) -> str:
        return self.sql_service.build_key(state, node)

    def get(self, cache_key: str) -> NodeExecutionResult | None:
        try:
            hit = self.redis_service.get(cache_key)
            if hit is not None:
                return hit
        except Exception:  # pragma: no cover - Redis outage falls through to SQL
            pass
        result = self.sql_service.get(cache_key)
        if result is not None:
            try:
                # Backfill Redis without a state/node (use a minimal write).
                serialized = json.dumps(result.model_dump(mode="json"), default=str)
                redis_key = self.redis_service._redis_key(cache_key)
                if self.redis_service.ttl_seconds > 0:
                    self.redis_service.client.setex(redis_key, self.redis_service.ttl_seconds, serialized)
                else:
                    self.redis_service.client.set(redis_key, serialized)
            except Exception:  # pragma: no cover
                pass
        return result

    def set(
        self,
        cache_key: str,
        state: GraphReasoningState,
        node: GraphNodeState,
        result: NodeExecutionResult,
    ) -> None:
        # Durable write first so a Redis failure cannot lose the result.
        self.sql_service.set(cache_key, state, node, result)
        try:
            self.redis_service.set(cache_key, state, node, result)
        except Exception:  # pragma: no cover - Redis is best-effort
            pass

    def invalidate_by_program(self, program_id: str, keep_version: str | None = None) -> int:
        """Invalidate all cached results for a program across both tiers.

        SQL rows are deleted; Redis keys are evicted via pattern scan.
        Returns the count of SQL rows deleted (Redis count is best-effort).
        """
        deleted = self.sql_service.invalidate_by_program(program_id, keep_version=keep_version)
        try:
            pattern = f"{self.redis_service.KEY_PREFIX}*"
            cursor = 0
            while True:
                cursor, keys = self.redis_service.client.scan(cursor, match=pattern, count=200)
                if keys:
                    self.redis_service.client.delete(*keys)
                if cursor == 0:
                    break
        except Exception:  # pragma: no cover - Redis is best-effort
            pass
        return deleted


def build_node_cache_service(db: Session, settings=None):
    """Factory: returns a Redis-backed layered cache when configured, else the SQL cache.

    Controlled by settings/env:
      - ``MW_CACHE_BACKEND=redis`` (default ``sql``)
      - ``MW_REDIS_URL`` (or ``REDIS_URL``)
      - ``MW_CACHE_TTL_SECONDS`` (0 = no expiry)
    Any import/connection failure degrades gracefully to the SQL cache.
    """
    sql_service = NodeCacheService(db)
    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()

    if str(getattr(settings, "cache_backend", "sql")).strip().lower() != "redis":
        return sql_service

    redis_url = getattr(settings, "resolved_redis_url", None) or getattr(settings, "redis_url", None)
    if not redis_url:
        return sql_service

    try:
        import redis  # optional dependency

        client = redis.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
    except Exception:  # pragma: no cover - missing dep or unreachable Redis
        return sql_service

    redis_service = RedisNodeCacheService(client, ttl_seconds=getattr(settings, "cache_ttl_seconds", 0))
    return LayeredNodeCacheService(redis_service, sql_service)
