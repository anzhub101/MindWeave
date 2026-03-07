from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MindWeave"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./mindweave.db"
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    force_https: bool = False
    storage_backend: str = "local"
    llm_provider: str = "k2"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    k2_api_key: str | None = None
    k2_model: str = "MBZUAI-IFM/K2-Think-v2"
    k2_chat_base_url: str = "https://api.k2think.ai/v1/chat/completions"
    k2_agent_base_url: str = "https://api.k2think.ai/v1/chat/completions"
    k2_temperature: float = 0.8
    deterministic_temperature: float = 0.0
    k2_reasoning_effort: str = "high"
    k2_top_p: float = 1.0
    deterministic_seed: int = 7
    vector_backend: str = "local"
    pinecone_api_key: str | None = None
    pinecone_index_name: str = "mindweave-knowledge"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"
    pinecone_embed_model: str = "llama-text-embed-v2"
    pinecone_metric: str = "cosine"
    pinecone_text_field: str = "chunk_text"
    pinecone_namespace_prefix: str = "task_"
    pinecone_consistency_wait_seconds: float = 10.0
    pinecone_auto_create_index: bool = True
    pinecone_timeout_seconds: int = 300
    supabase_url: str | None = None
    supabase_publishable_key: str | None = None
    supabase_secret_key: str | None = None
    supabase_uploads_bucket: str = "mindweave-documents"
    supabase_audit_bucket: str = "mindweave-audits"
    supabase_db_password: str | None = None
    supabase_db_user: str = "postgres"
    supabase_db_host: str | None = None
    supabase_db_port: int = 5432
    chunkr_api_key: str | None = None
    chunkr_url: str | None = None
    chunkr_enable_pdf_ocr_fallback: bool = True
    chunkr_pdf_char_threshold: int = 120
    chunkr_ocr_strategy: str = "Auto"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    storage_root: Path = Path(__file__).resolve().parents[2] / "data"
    artifact_root: Path = Path(__file__).resolve().parents[1] / "design_artifacts"
    sample_data_root: Path = Path(__file__).resolve().parents[3] / "sample_data"
    generated_artifact_root: Path = Path(__file__).resolve().parents[2] / "data" / "generated_artifacts"
    requirements_markdown_path: Path = Path(__file__).resolve().parents[3] / "docs" / "requirements-planning.md"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="MW_", extra="ignore")

    @property
    def resolved_pinecone_api_key(self) -> str | None:
        return self.pinecone_api_key or os.getenv("PINECONE_API_KEY")

    @property
    def resolved_supabase_key(self) -> str | None:
        return self.supabase_secret_key or self.supabase_publishable_key

    @property
    def supabase_project_ref(self) -> str | None:
        if not self.supabase_url:
            return None
        hostname = urlparse(self.supabase_url).hostname or ""
        parts = hostname.split(".")
        return parts[0] if parts else None

    @property
    def resolved_database_url(self) -> str:
        explicit_database_url = os.getenv("MW_DATABASE_URL")
        if explicit_database_url:
            return self._normalize_database_url(explicit_database_url)
        if self.supabase_project_ref and self.supabase_db_password:
            host = self.supabase_db_host or f"db.{self.supabase_project_ref}.supabase.co"
            password = quote_plus(self.supabase_db_password)
            return self._normalize_database_url(
                f"postgresql+psycopg://{self.supabase_db_user}:{password}"
                f"@{host}:{self.supabase_db_port}/postgres"
            )
        return self._normalize_database_url(self.database_url)

    @staticmethod
    def _normalize_database_url(database_url: str) -> str:
        if database_url.startswith("postgresql://"):
            return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
