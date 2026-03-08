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
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    retrieval_score: float = 0.0
    source_type: str = "retrieved"


class KnowledgeBase:
    def __init__(self, documents: list[DocumentRecord], task_id: str | None = None, vector_store=None) -> None:
        self.documents = documents
        self.task_id = task_id
        self.vector_store = vector_store
        self.chunks = self._build_chunks(documents)
        if self.vector_store is not None and self.task_id is not None:
            self.vector_store.index_chunks(self.task_id, self.chunks)

    def retrieve(self, query: str, top_k: int = 3, evidence_scope: dict | None = None) -> list[KnowledgeChunk]:
        query_terms = set(self._terms(query))
        allowed_documents = set()
        if isinstance(evidence_scope, dict):
            raw_documents = evidence_scope.get("document_ids", [])
            if isinstance(raw_documents, list):
                allowed_documents = {str(value) for value in raw_documents if str(value).strip()}
        similarity_scores = (
            self.vector_store.similarity_map(self.task_id, query, top_k=max(top_k * 4, 12))
            if self.vector_store is not None and self.task_id is not None
            else {}
        )
        scored: list[tuple[float, KnowledgeChunk]] = []
        for chunk in self.chunks:
            if allowed_documents and chunk.document_id not in allowed_documents:
                continue
            chunk_terms = set(self._terms(chunk.text))
            lexical_score = len(query_terms.intersection(chunk_terms))
            semantic_score = float(similarity_scores.get(chunk.id, 0.0))
            score = float(lexical_score * 10) + (semantic_score * 100.0)
            if score:
                scored.append((score, chunk.model_copy(update={"retrieval_score": score})))
        scored.sort(key=lambda item: (-item[0], item[1].document_name, item[1].id))
        return [chunk for _, chunk in scored[:top_k]]

    def by_name(self, name_fragment: str) -> list[DocumentRecord]:
        fragment = name_fragment.lower()
        return [document for document in self.documents if fragment in document.name.lower()]

    def _build_chunks(self, documents: list[DocumentRecord]) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []
        for document in documents:
            page_texts = document.metadata.get("page_texts", []) if isinstance(document.metadata, dict) else []
            if isinstance(page_texts, list) and page_texts:
                for page_index, page_text in enumerate(page_texts):
                    page_value = str(page_text).strip()
                    if not page_value:
                        continue
                    chunks.append(
                        KnowledgeChunk(
                            id=f"{document.id}_page_{page_index + 1}",
                            document_id=document.id,
                            document_name=document.name,
                            text=page_value,
                            page=page_index + 1,
                            char_start=0,
                            char_end=len(page_value),
                        )
                    )
                continue

            parts = self._chunk_text(document.extracted_text)
            if not parts:
                parts = [(document.extracted_text, 0, len(document.extracted_text))]
            for index, (part, char_start, char_end) in enumerate(parts):
                chunks.append(
                    KnowledgeChunk(
                        id=f"{document.id}_chunk_{index}",
                        document_id=document.id,
                        document_name=document.name,
                        text=part,
                        char_start=char_start,
                        char_end=char_end,
                    )
                )
        return chunks

    @staticmethod
    def _chunk_text(text: str, target_size: int = 380) -> list[tuple[str, int, int]]:
        parts: list[tuple[str, int, int]] = []
        current = ""
        current_start = 0
        cursor = 0
        for block in re.split(r"\n\s*\n", text):
            candidate = block.strip()
            if not candidate:
                cursor += len(block) + 2
                continue
            if len(current) + len(candidate) > target_size and current:
                parts.append((current.strip(), current_start, current_start + len(current.strip())))
                current = candidate
                current_start = cursor
            else:
                if not current:
                    current_start = cursor
                current = f"{current}\n{candidate}".strip()
            cursor += len(block) + 2
        if current:
            parts.append((current.strip(), current_start, current_start + len(current.strip())))
        return parts

    @staticmethod
    def _terms(value: str) -> Iterable[str]:
        return [term for term in re.findall(r"[A-Za-z0-9]+", value.lower()) if len(term) > 2]
