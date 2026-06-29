from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MindWeave"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./mindweave.db"
    # TrustedHostMiddleware will reject requests whose Host header isn't here.
    # In hosted environments (e.g. Render), the public hostname is typically `*.onrender.com`.
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "*.onrender.com", "mindweave.onrender.com"]
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
    deterministic_seed: int = 42
    strict_local_model_id: str = "mindweave-local-deterministic"
    strict_local_model_version: str = "dev"
    strict_inference_engine_version: str = "mock-engine-1.0"
    strict_cuda_stack: str = "cpu"
    strict_instance_type: str = "local-dev"
    strict_disable_dynamic_batching: bool = True
    strict_parallelism: int = 1
    strict_local_endpoint: str = "local://mindweave-strict"
    web_search_enabled: bool = True
    web_search_backend: str = "mcp"
    web_search_transport_fallback: str = "api"
    web_search_top_k: int = 5
    web_search_timeout_seconds: float = 20.0
    brave_api_key: str | None = None
    brave_search_url: str = "https://api.search.brave.com/res/v1/web/search"
    brave_mcp_command: str | None = "npx -y brave-search-mcp"
    brave_mcp_tool_name: str | None = None
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
    cache_backend: str = "sql"
    redis_url: str | None = None
    cache_ttl_seconds: int = 0
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    storage_root: Path = Path(__file__).resolve().parents[2] / "data"
    artifact_root: Path = Path(__file__).resolve().parents[1] / "design_artifacts"
    sample_data_root: Path = Path(__file__).resolve().parents[3] / "sample_data"
    generated_artifact_root: Path = Path(__file__).resolve().parents[2] / "data" / "generated_artifacts"
    requirements_markdown_path: Path = Path(__file__).resolve().parents[3] / "docs" / "requirements-planning.md"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="MW_", extra="ignore")

    @field_validator("allowed_hosts", "cors_origins", mode="before")
    @classmethod
    def _parse_csv_or_json_list(cls, v):
        # Render dashboard env vars are often entered as comma-separated strings.
        # Pydantic will already handle real JSON lists (e.g. '["a","b"]').
        if isinstance(v, str):
            raw = v.strip()
            if not raw:
                return []
            if raw.startswith("[") and raw.endswith("]"):
                return v
            return [item.strip() for item in raw.split(",") if item.strip()]
        return v

    @property
    def resolved_pinecone_api_key(self) -> str | None:
        return self.pinecone_api_key or os.getenv("PINECONE_API_KEY")

    @property
    def resolved_brave_api_key(self) -> str | None:
        return self.brave_api_key or os.getenv("BRAVE_API_KEY")

    @property
    def resolved_redis_url(self) -> str | None:
        return self.redis_url or os.getenv("REDIS_URL")

    @property
    def resolved_k2_api_key(self) -> str | None:
        return self.k2_api_key or os.getenv("K2_API_KEY")

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
