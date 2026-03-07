from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.db.base import Base
from app.services.task_service import TaskService


async def main() -> None:
    settings = get_settings()
    engine = create_engine(
        settings.resolved_database_url,
        connect_args={"check_same_thread": False} if settings.resolved_database_url.startswith("sqlite") else {},
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    prompt = "Perform a financial audit for Invisium FY2026 based on the uploaded documents."

    with SessionLocal() as db:
        service = TaskService(db)
        response = await service.execute_task(
            prompt=prompt,
            deterministic=True,
            auto_approve_human_review=True,
            use_sample_data=True,
            files=[],
        )

    print(json.dumps(
        {
            "task_id": response.task_id,
            "status": response.status,
            "program_id": response.program_id,
            "domain": response.domain,
            "node_count": len(response.nodes),
            "final_summary": response.final_summary,
        },
        indent=2,
        default=str,
    ))


if __name__ == "__main__":
    asyncio.run(main())
