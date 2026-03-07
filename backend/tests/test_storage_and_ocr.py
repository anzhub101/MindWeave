from __future__ import annotations

from types import SimpleNamespace

from app.core.config import Settings
from app.services.document_processor import DocumentProcessor
from app.services.ocr_service import ChunkrOCRService
from app.services.storage_service import StorageService


class FakeBucket:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes, dict | None]] = []

    def upload(self, path: str, file, file_options=None):
        data = file if isinstance(file, bytes) else bytes(file)
        self.uploads.append((path, data, file_options))
        return {"path": path}


class FakeStorageClient:
    def __init__(self) -> None:
        self.buckets = [{"id": "mindweave-documents"}, {"id": "mindweave-audits"}]
        self.bucket = FakeBucket()

    def list_buckets(self):
        return self.buckets

    def create_bucket(self, bucket_id, options=None):
        self.buckets.append({"id": bucket_id})
        return {"id": bucket_id}

    def from_(self, _bucket_name):
        return self.bucket


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.storage = FakeStorageClient()


def test_storage_service_supabase_backend_returns_remote_locator(tmp_path):
    settings = Settings(
        storage_backend="supabase",
        supabase_url="https://example.supabase.co",
        supabase_secret_key="secret",
    )
    service = StorageService(settings=settings, storage_root=tmp_path, client=FakeSupabaseClient())

    result = service.store_text("uploads", "task1/report.txt", "hello world")

    assert result.locator == "supabase://mindweave-documents/uploads/task1/report.txt"
    assert result.local_path.exists()


def test_settings_derives_supabase_database_url():
    settings = Settings(
        supabase_url="https://coiqsprscdmovszhyega.supabase.co",
        supabase_db_password="Mindweave@2001",
    )

    assert settings.resolved_database_url == (
        "postgresql+psycopg://postgres:Mindweave%402001@db.coiqsprscdmovszhyega.supabase.co:5432/postgres"
    )


def test_settings_normalizes_plain_postgresql_urls(monkeypatch):
    monkeypatch.setenv("MW_DATABASE_URL", "postgresql://postgres:secret@db.example.supabase.co:5432/postgres")
    settings = Settings()

    assert settings.resolved_database_url == "postgresql+psycopg://postgres:secret@db.example.supabase.co:5432/postgres"


def test_document_processor_uses_chunkr_fallback_for_low_text(tmp_path, monkeypatch):
    settings = Settings(
        chunkr_api_key="chunkr-secret",
        chunkr_enable_pdf_ocr_fallback=True,
        chunkr_pdf_char_threshold=20,
    )
    ocr_service = ChunkrOCRService(settings=settings, client=SimpleNamespace())
    ocr_service.extract_text = lambda raw, filename: ("OCR extracted content", {"provider": "chunkr", "used": True})

    processor = DocumentProcessor(
        storage_service=StorageService(settings=Settings(), storage_root=tmp_path),
        ocr_service=ocr_service,
    )
    processor.settings = settings
    monkeypatch.setattr(
        "app.services.document_processor.PdfReader",
        lambda _stream: SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: "")]),
    )

    text, metadata = processor._extract_text("scan.pdf", b"%PDF")

    assert text == "OCR extracted content"
    assert metadata["ocr_used"] is True
