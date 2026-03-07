from __future__ import annotations

import re
from typing import Iterable

from pydantic import BaseModel

from app.models.runtime import DocumentRecord


class KnowledgeChunk(BaseModel):
    id: str
    document_id: str
    document_name: str
    text: str


class KnowledgeBase:
    def __init__(self, documents: list[DocumentRecord], task_id: str | None = None, vector_store=None) -> None:
        self.documents = documents
        self.task_id = task_id
        self.vector_store = vector_store
        self.chunks = self._build_chunks(documents)
        if self.vector_store is not None and self.task_id is not None:
            self.vector_store.index_chunks(self.task_id, self.chunks)

    def retrieve(self, query: str, top_k: int = 3) -> list[KnowledgeChunk]:
        query_terms = set(self._terms(query))
        similarity_scores = (
            self.vector_store.similarity_map(self.task_id, query, top_k=max(top_k * 4, 12))
            if self.vector_store is not None and self.task_id is not None
            else {}
        )
        scored: list[tuple[int, KnowledgeChunk]] = []
        for chunk in self.chunks:
            chunk_terms = set(self._terms(chunk.text))
            lexical_score = len(query_terms.intersection(chunk_terms))
            semantic_score = int(similarity_scores.get(chunk.id, 0.0) * 100)
            score = lexical_score * 10 + semantic_score
            if score:
                scored.append((score, chunk))
        scored.sort(key=lambda item: (-item[0], item[1].document_name, item[1].id))
        return [chunk for _, chunk in scored[:top_k]]

    def by_name(self, name_fragment: str) -> list[DocumentRecord]:
        fragment = name_fragment.lower()
        return [document for document in self.documents if fragment in document.name.lower()]

    def _build_chunks(self, documents: list[DocumentRecord]) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []
        for document in documents:
            parts = self._chunk_text(document.extracted_text)
            if not parts:
                parts = [document.extracted_text]
            for index, part in enumerate(parts):
                chunks.append(
                    KnowledgeChunk(
                        id=f"{document.id}_chunk_{index}",
                        document_id=document.id,
                        document_name=document.name,
                        text=part,
                    )
                )
        return chunks

    @staticmethod
    def _chunk_text(text: str, target_size: int = 380) -> list[str]:
        parts: list[str] = []
        current = ""
        for block in re.split(r"\n\s*\n", text):
            candidate = block.strip()
            if not candidate:
                continue
            if len(current) + len(candidate) > target_size and current:
                parts.append(current.strip())
                current = candidate
            else:
                current = f"{current}\n{candidate}".strip()
        if current:
            parts.append(current.strip())
        return parts

    @staticmethod
    def _terms(value: str) -> Iterable[str]:
        return [term for term in re.findall(r"[A-Za-z0-9]+", value.lower()) if len(term) > 2]
