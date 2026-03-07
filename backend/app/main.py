from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.db.session import init_db


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        if get_settings().force_https:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


settings = get_settings()
app = FastAPI(title=settings.app_name)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
if settings.force_https:
    app.add_middleware(HTTPSRedirectMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(router, prefix=settings.api_prefix)


@app.on_event("startup")
def on_startup() -> None:
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    init_db()
