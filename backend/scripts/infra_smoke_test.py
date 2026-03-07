from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy import create_engine, text

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.services.ocr_service import ChunkrOCRService
from app.services.storage_service import StorageService


def main() -> None:
    settings = get_settings()
    result: dict[str, object] = {"storage": None, "database": None, "chunkr": None}

    if settings.storage_backend.lower() == "supabase":
        storage = StorageService(settings=settings)
        upload = storage.store_text("uploads", "smoke/live-check.txt", "MindWeave storage smoke test")
        audit = storage.store_json("audit_packages", "smoke/live-check.json", {"ok": True})
        result["storage"] = {
            "upload_locator": upload.locator,
            "audit_locator": audit.locator,
        }

    try:
        engine = create_engine(settings.resolved_database_url, future=True)
        with engine.connect() as conn:
            result["database"] = {"select_1": conn.execute(text("select 1")).scalar()}
    except Exception as exc:
        result["database"] = {"error": str(exc)}

    if settings.chunkr_api_key:
        image = Image.new("RGB", (900, 240), "white")
        draw = ImageDraw.Draw(image)
        draw.text((50, 95), "MindWeave OCR Test 2026", fill="black")
        buffer = BytesIO()
        image.save(buffer, format="PDF")
        ocr = ChunkrOCRService(settings=settings)
        text_content, metadata = ocr.extract_text(buffer.getvalue(), "ocr-smoke.pdf")
        result["chunkr"] = {"preview": text_content[:120], "metadata": metadata}

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
