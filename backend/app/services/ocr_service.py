from __future__ import annotations

from app.core.config import Settings, get_settings


class ChunkrOCRService:
    def __init__(self, settings: Settings | None = None, client=None) -> None:
        self.settings = settings or get_settings()
        self._client = client

    def enabled(self) -> bool:
        return bool(self.settings.chunkr_enable_pdf_ocr_fallback and self.settings.chunkr_api_key)

    def extract_text(self, raw: bytes, filename: str) -> tuple[str, dict]:
        if not self.enabled():
            return "", {"provider": "chunkr", "used": False, "reason": "disabled"}

        from chunkr_ai import Chunkr
        from chunkr_ai.models import Configuration, OcrStrategy

        client = self._client or Chunkr(
            url=self.settings.chunkr_url,
            api_key=self.settings.chunkr_api_key,
            raise_on_failure=False,
        )
        task = client.upload(
            raw,
            Configuration(ocr_strategy=OcrStrategy(self.settings.chunkr_ocr_strategy)),
            filename=filename,
        )
        task = task.poll()
        text = task.markdown().strip()
        metadata = {
            "provider": "chunkr",
            "used": bool(text),
            "status": getattr(task, "status", None),
            "task_id": getattr(task, "task_id", None),
            "page_count": getattr(getattr(task, "output", None), "page_count", None),
        }
        return text, metadata
