from __future__ import annotations

import math
import time
from hashlib import sha256
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import EmbeddingRecord
from app.services.knowledge_base import KnowledgeChunk


class VectorStore:
    def __init__(
        self,
        db: Session,
        dimensions: int = 32,
        settings: Settings | None = None,
        pinecone_factory: Callable[[str], Any] | None = None,
        sleep_func: Callable[[float], None] | None = None,
    ) -> None:
        self.db = db
        self.dimensions = dimensions
        self.settings = settings or get_settings()
        self.backend = self.settings.vector_backend.lower().strip() or "local"
        self._pinecone_factory = pinecone_factory
        self._sleep = sleep_func or time.sleep
        self._pinecone_client: Any | None = None
        self._pinecone_index: Any | None = None

        if self.backend not in {"local", "pinecone"}:
            raise ValueError(f"Unsupported vector backend: {self.settings.vector_backend}")

    def index_chunks(self, task_id: str, chunks: list[KnowledgeChunk]) -> None:
        if not chunks:
            return
        if self.backend == "pinecone":
            self._index_chunks_pinecone(task_id, chunks)
            return
        for chunk in chunks:
            vector = self.embed(chunk.text)
            existing = (
                self.db.query(EmbeddingRecord)
                .filter(EmbeddingRecord.task_id == task_id, EmbeddingRecord.chunk_id == chunk.id)
                .one_or_none()
            )
            payload = {
                "task_id": task_id,
                "document_id": chunk.document_id,
                "chunk_id": chunk.id,
                "vector": vector,
                "text_excerpt": chunk.text[:280],
                "payload": {"document_name": chunk.document_name},
            }
            if existing is None:
                self.db.add(EmbeddingRecord(**payload))
            else:
                existing.vector = vector
                existing.text_excerpt = payload["text_excerpt"]
                existing.payload = payload["payload"]
        self.db.commit()

    def similarity_map(self, task_id: str, query: str, top_k: int | None = None) -> dict[str, float]:
        if self.backend == "pinecone":
            return self._similarity_map_pinecone(task_id, query, top_k=top_k or 12)
        query_vector = self.embed(query)
        records = self.db.query(EmbeddingRecord).filter(EmbeddingRecord.task_id == task_id).all()
        scores: dict[str, float] = {}
        for record in records:
            scores[record.chunk_id] = self._cosine_similarity(query_vector, record.vector)
        return scores

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        terms = [term for term in text.lower().split() if term]
        if not terms:
            return vector
        for term in terms:
            digest = sha256(term.encode("utf-8")).digest()
            index = digest[0] % self.dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        return sum(a * b for a, b in zip(left, right))

    def _index_chunks_pinecone(self, task_id: str, chunks: list[KnowledgeChunk]) -> None:
        if self._pinecone_task_already_indexed(task_id, expected_count=len(chunks)):
            return

        index = self._get_pinecone_index()
        namespace = self._pinecone_namespace(task_id)
        field_name = self.settings.pinecone_text_field
        payload_template = {
            "backend": "pinecone",
            "index_name": self.settings.pinecone_index_name,
            "namespace": namespace,
        }

        records = [
            {
                "_id": chunk.id,
                field_name: chunk.text,
                "task_id": task_id,
                "document_id": chunk.document_id,
                "document_name": chunk.document_name,
            }
            for chunk in chunks
        ]
        for start in range(0, len(records), 96):
            index.upsert_records(namespace=namespace, records=records[start : start + 96])

        for chunk in chunks:
            existing = (
                self.db.query(EmbeddingRecord)
                .filter(EmbeddingRecord.task_id == task_id, EmbeddingRecord.chunk_id == chunk.id)
                .one_or_none()
            )
            payload = {
                "task_id": task_id,
                "document_id": chunk.document_id,
                "chunk_id": chunk.id,
                "vector": [],
                "text_excerpt": chunk.text[:280],
                "payload": {**payload_template, "document_name": chunk.document_name},
            }
            if existing is None:
                self.db.add(EmbeddingRecord(**payload))
            else:
                existing.vector = []
                existing.text_excerpt = payload["text_excerpt"]
                existing.payload = payload["payload"]
        self.db.commit()

        wait_seconds = max(self.settings.pinecone_consistency_wait_seconds, 0.0)
        if wait_seconds:
            self._sleep(wait_seconds)

    def _similarity_map_pinecone(self, task_id: str, query: str, top_k: int) -> dict[str, float]:
        index = self._get_pinecone_index()
        response = index.search_records(
            namespace=self._pinecone_namespace(task_id),
            query={
                "inputs": {"text": query},
                "top_k": max(top_k, 1),
            },
            fields=[self.settings.pinecone_text_field, "document_id", "document_name", "task_id"],
        )
        hits = getattr(getattr(response, "result", None), "hits", []) or []
        scores: dict[str, float] = {}
        for hit in hits:
            chunk_id = getattr(hit, "_id", None)
            score = getattr(hit, "_score", 0.0)
            if chunk_id:
                scores[str(chunk_id)] = float(score or 0.0)
        return scores

    def _pinecone_namespace(self, task_id: str) -> str:
        return f"{self.settings.pinecone_namespace_prefix}{task_id}"

    def _pinecone_task_already_indexed(self, task_id: str, expected_count: int) -> bool:
        count = (
            self.db.query(EmbeddingRecord)
            .filter(EmbeddingRecord.task_id == task_id)
            .count()
        )
        return count >= expected_count > 0

    def _get_pinecone_client(self) -> Any:
        if self._pinecone_client is not None:
            return self._pinecone_client

        api_key = self.settings.resolved_pinecone_api_key
        if not api_key:
            raise ValueError("MW_PINECONE_API_KEY or PINECONE_API_KEY is required when MW_VECTOR_BACKEND=pinecone")

        if self._pinecone_factory is not None:
            self._pinecone_client = self._pinecone_factory(api_key)
            return self._pinecone_client

        from pinecone import Pinecone

        self._pinecone_client = Pinecone(api_key=api_key)
        return self._pinecone_client

    def _get_pinecone_index(self) -> Any:
        if self._pinecone_index is not None:
            return self._pinecone_index

        client = self._get_pinecone_client()
        index_name = self.settings.pinecone_index_name

        if not client.has_index(index_name):
            if not self.settings.pinecone_auto_create_index:
                raise ValueError(
                    f"Pinecone index '{index_name}' does not exist and MW_PINECONE_AUTO_CREATE_INDEX is disabled"
                )
            from pinecone import IndexEmbed

            client.create_index_for_model(
                name=index_name,
                cloud=self.settings.pinecone_cloud,
                region=self.settings.pinecone_region,
                embed=IndexEmbed(
                    model=self.settings.pinecone_embed_model,
                    field_map={"text": self.settings.pinecone_text_field},
                    metric=self.settings.pinecone_metric,
                ),
                timeout=self.settings.pinecone_timeout_seconds,
            )

        description = client.describe_index(index_name)
        host = getattr(description, "host", None)
        if not host:
            raise RuntimeError(f"Pinecone index '{index_name}' did not return a host")
        self._pinecone_index = client.Index(host=host)
        return self._pinecone_index
