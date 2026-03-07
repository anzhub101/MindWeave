from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings, get_settings


@dataclass
class StorageWriteResult:
    locator: str
    local_path: Path
    bucket: str | None = None
    key: str | None = None


class StorageService:
    def __init__(self, settings: Settings | None = None, storage_root: Path | None = None, client=None) -> None:
        self.settings = settings or get_settings()
        self.backend = self.settings.storage_backend.lower().strip() or "local"
        self.storage_root = storage_root or self.settings.storage_root
        self._client = client
        self._verified_buckets: set[str] = set()

    def store_bytes(self, category: str, relative_path: str, data: bytes, content_type: str) -> StorageWriteResult:
        local_path = self._local_path(category, relative_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self._make_writable(local_path)
        local_path.write_bytes(data)
        self._freeze_file(local_path)

        if self.backend != "supabase":
            return StorageWriteResult(locator=str(local_path), local_path=local_path)

        bucket = self._bucket_for_category(category)
        key = self._remote_key(category, relative_path)
        self._ensure_bucket(bucket)
        self._get_client().storage.from_(bucket).upload(
            key,
            data,
            file_options={"content-type": content_type, "upsert": "true"},
        )
        return StorageWriteResult(
            locator=f"supabase://{bucket}/{key}",
            local_path=local_path,
            bucket=bucket,
            key=key,
        )

    def store_text(self, category: str, relative_path: str, text: str, content_type: str = "text/plain") -> StorageWriteResult:
        return self.store_bytes(category, relative_path, text.encode("utf-8"), content_type)

    def store_json(self, category: str, relative_path: str, payload: dict) -> StorageWriteResult:
        return self.store_text(category, relative_path, json.dumps(payload, indent=2), "application/json")

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.settings.supabase_url or not self.settings.resolved_supabase_key:
            raise ValueError("MW_SUPABASE_URL and a Supabase key are required when MW_STORAGE_BACKEND=supabase")
        from supabase import create_client

        self._client = create_client(self.settings.supabase_url, self.settings.resolved_supabase_key)
        return self._client

    def _ensure_bucket(self, bucket: str) -> None:
        if bucket in self._verified_buckets:
            return
        client = self._get_client()
        buckets = client.storage.list_buckets()
        bucket_ids = {
            item["id"] if isinstance(item, dict) else getattr(item, "id", None)
            for item in buckets
        }
        if bucket not in bucket_ids:
            client.storage.create_bucket(bucket, options={"public": False})
        self._verified_buckets.add(bucket)

    def _bucket_for_category(self, category: str) -> str:
        if category == "uploads":
            return self.settings.supabase_uploads_bucket
        return self.settings.supabase_audit_bucket

    @staticmethod
    def _remote_key(category: str, relative_path: str) -> str:
        return f"{category}/{relative_path}".replace("\\", "/")

    def _local_path(self, category: str, relative_path: str) -> Path:
        return self.storage_root / category / relative_path

    @staticmethod
    def _freeze_file(path: Path) -> None:
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        except PermissionError:
            pass

    @staticmethod
    def _make_writable(path: Path) -> None:
        if not path.exists():
            return
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
        except PermissionError:
            pass
