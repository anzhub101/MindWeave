from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.services.knowledge_base import KnowledgeChunk
from app.services.vector_store import VectorStore


class FakePineconeIndex:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, list[dict]]] = []
        self.searches: list[tuple[str, dict, list[str] | None]] = []

    def upsert_records(self, namespace: str, records: list[dict]):
        self.upserts.append((namespace, records))
        return {"upserted_count": len(records)}

    def search_records(self, namespace: str, query: dict, fields: list[str] | None = None):
        self.searches.append((namespace, query, fields))
        return SimpleNamespace(
            result=SimpleNamespace(
                hits=[
                    SimpleNamespace(_id="chunk_alpha", _score=0.91, fields={"chunk_text": "alpha"}),
                    SimpleNamespace(_id="chunk_beta", _score=0.24, fields={"chunk_text": "beta"}),
                ]
            )
        )


class FakePineconeClient:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.index = FakePineconeIndex()

    def has_index(self, name: str) -> bool:
        return bool(self.created)

    def create_index_for_model(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(host="https://example-index")

    def describe_index(self, name: str):
        return SimpleNamespace(host="https://example-index")

    def Index(self, host: str):
        return self.index


def test_pinecone_vector_store_indexes_and_searches_with_namespace():
    fake_client = FakePineconeClient()
    settings = Settings(
        vector_backend="pinecone",
        pinecone_api_key="test-key",
        pinecone_index_name="mindweave-test",
        pinecone_text_field="chunk_text",
        pinecone_consistency_wait_seconds=0.0,
    )
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    chunks = [
        KnowledgeChunk(id="chunk_alpha", document_id="doc1", document_name="Doc 1", text="alpha evidence"),
        KnowledgeChunk(id="chunk_beta", document_id="doc1", document_name="Doc 1", text="beta evidence"),
    ]

    with session_local() as db_session:
        store = VectorStore(
            db_session,
            settings=settings,
            pinecone_factory=lambda _api_key: fake_client,
            sleep_func=lambda _seconds: None,
        )
        store.index_chunks("task123", chunks)
        scores = store.similarity_map("task123", "alpha", top_k=2)

    assert fake_client.created
    namespace, records = fake_client.index.upserts[0]
    assert namespace == "task_task123"
    assert records[0]["chunk_text"] == "alpha evidence"
    assert scores == {"chunk_alpha": 0.91, "chunk_beta": 0.24}
