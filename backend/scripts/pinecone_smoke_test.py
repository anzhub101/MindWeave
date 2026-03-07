from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.db.base import Base
from app.services.knowledge_base import KnowledgeChunk
from app.services.vector_store import VectorStore


def main() -> None:
    settings = get_settings()
    if settings.vector_backend.lower() != "pinecone":
        raise SystemExit("Set MW_VECTOR_BACKEND=pinecone before running the Pinecone smoke test.")
    if not settings.resolved_pinecone_api_key:
        raise SystemExit("Set MW_PINECONE_API_KEY or PINECONE_API_KEY before running the Pinecone smoke test.")

    engine = create_engine(
        settings.resolved_database_url,
        connect_args={"check_same_thread": False} if settings.resolved_database_url.startswith("sqlite") else {},
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    task_id = f"pinecone_smoke_{uuid4().hex[:8]}"
    chunks = [
        KnowledgeChunk(
            id="rec1",
            document_id="quickstart",
            document_name="quickstart.txt",
            text="The Eiffel Tower was completed in 1889 and stands in Paris, France.",
        ),
        KnowledgeChunk(
            id="rec2",
            document_id="quickstart",
            document_name="quickstart.txt",
            text="Photosynthesis allows plants to convert sunlight into energy.",
        ),
        KnowledgeChunk(
            id="rec3",
            document_id="quickstart",
            document_name="quickstart.txt",
            text="Shakespeare wrote many famous plays, including Hamlet and Macbeth.",
        ),
    ]

    with session_local() as db:
        store = VectorStore(db)
        store.index_chunks(task_id, chunks)
        scores = store.similarity_map(task_id, "Which city is the Eiffel Tower in?", top_k=3)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    print(
        json.dumps(
            {
                "task_id": task_id,
                "backend": settings.vector_backend,
                "index_name": settings.pinecone_index_name,
                "namespace": f"{settings.pinecone_namespace_prefix}{task_id}",
                "top_match": ranked[0][0] if ranked else None,
                "scores": ranked,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
