from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.config import get_settings


class WebSearchResult(BaseModel):
    result_id: str
    title: str
    url: str
    snippet: str = ""
    provider: str = "brave"
    score: float | None = None


@dataclass
class MCPResponse:
    payload: dict[str, Any]


class WebSearchService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def enabled(self) -> bool:
        return bool(self.settings.web_search_enabled and self.settings.resolved_brave_api_key)

    def search(self, query: str, top_k: int | None = None) -> list[WebSearchResult]:
        if not self.enabled():
            return []

        count = max(1, min(int(top_k or self.settings.web_search_top_k), 10))
        if self.settings.web_search_backend == "mcp" and self.settings.brave_mcp_command:
            try:
                results = self._search_via_mcp(query, count)
                if results:
                    return results
            except Exception:
                if self.settings.web_search_transport_fallback != "api":
                    return []
        try:
            return self._search_via_brave_api(query, count)
        except Exception:
            return []

    def _search_via_brave_api(self, query: str, top_k: int) -> list[WebSearchResult]:
        response = httpx.get(
            self.settings.brave_search_url,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": str(self.settings.resolved_brave_api_key),
            },
            params={"q": query, "count": top_k, "search_lang": "en"},
            timeout=self.settings.web_search_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        raw_results = (((payload.get("web") or {}).get("results")) or [])[:top_k]
        return [
            WebSearchResult(
                result_id=str(item.get("url") or item.get("profile") or f"web_{index}"),
                title=str(item.get("title") or item.get("url") or f"Web result {index + 1}"),
                url=str(item.get("url") or ""),
                snippet=str(item.get("description") or item.get("snippet") or ""),
                provider="brave_api",
                score=float(item.get("page_age", 0.0) or 0.0) if isinstance(item.get("page_age"), (int, float)) else None,
            )
            for index, item in enumerate(raw_results)
            if str(item.get("url") or "").strip()
        ]

    def _search_via_mcp(self, query: str, top_k: int) -> list[WebSearchResult]:
        command = shlex.split(self.settings.brave_mcp_command)
        env = {
            **os.environ,
            "BRAVE_API_KEY": str(self.settings.resolved_brave_api_key),
        }
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        try:
            self._request(
                process,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "mindweave", "version": "0.1.0"},
                },
                request_id=1,
            )
            self._notify(process, "notifications/initialized", {})
            tools_response = self._request(process, "tools/list", {}, request_id=2)
            tools = ((tools_response.payload.get("result") or {}).get("tools")) or []
            tool_name = self._resolve_search_tool_name(tools)
            tool_response = self._request(
                process,
                "tools/call",
                {
                    "name": tool_name,
                    "arguments": {
                        "query": query,
                        "count": top_k,
                    },
                },
                request_id=3,
            )
            content = ((tool_response.payload.get("result") or {}).get("content")) or []
            parsed = self._parse_mcp_content(content)
            normalized = self._normalize_results(parsed)
            if normalized:
                return normalized[:top_k]
            raise ValueError("No usable results were returned by the Brave MCP server.")
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

    def _resolve_search_tool_name(self, tools: list[dict[str, Any]]) -> str:
        if self.settings.brave_mcp_tool_name:
            return self.settings.brave_mcp_tool_name
        for tool in tools:
            name = str(tool.get("name") or "")
            lowered = name.lower()
            if "search" in lowered and "local" not in lowered:
                return name
        raise ValueError("No Brave search tool was exposed by the configured MCP server.")

    def _parse_mcp_content(self, content: list[dict[str, Any]]) -> Any:
        text_parts: list[str] = []
        json_payloads: list[Any] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                text = str(item["text"]).strip()
                if not text:
                    continue
                try:
                    json_payloads.append(json.loads(text))
                except Exception:
                    text_parts.append(text)
            elif item.get("type") == "json":
                json_payloads.append(item.get("json"))
        if json_payloads:
            if len(json_payloads) == 1:
                return json_payloads[0]
            return json_payloads
        return "\n".join(text_parts).strip()

    def _normalize_results(self, payload: Any) -> list[WebSearchResult]:
        candidates: list[dict[str, Any]] = []
        if isinstance(payload, list):
            aggregated: list[WebSearchResult] = []
            for item in payload:
                if isinstance(item, dict):
                    aggregated.extend(self._normalize_results(item))
            return aggregated
        if isinstance(payload, dict):
            for key in ("results", "web", "items", "entries"):
                value = payload.get(key)
                if isinstance(value, list):
                    candidates = [item for item in value if isinstance(item, dict)]
                    break
                if isinstance(value, dict) and isinstance(value.get("results"), list):
                    candidates = [item for item in value["results"] if isinstance(item, dict)]
                    break
        if not candidates and isinstance(payload, str) and payload:
            return [
                WebSearchResult(
                    result_id="mcp_text_result",
                    title="Brave MCP Search Result",
                    url="",
                    snippet=payload,
                    provider="brave_mcp",
                )
            ]

        normalized: list[WebSearchResult] = []
        for index, item in enumerate(candidates):
            url = str(item.get("url") or item.get("link") or item.get("source") or "").strip()
            title = str(item.get("title") or item.get("name") or url or f"Web result {index + 1}")
            snippet = str(item.get("description") or item.get("snippet") or item.get("text") or "").strip()
            if not url and not snippet:
                continue
            normalized.append(
                WebSearchResult(
                    result_id=str(item.get("id") or url or f"web_{index}"),
                    title=title,
                    url=url,
                    snippet=snippet,
                    provider="brave_mcp",
                )
            )
        return normalized

    def _notify(self, process: subprocess.Popen[bytes], method: str, params: dict[str, Any]) -> None:
        self._send_message(process, {"jsonrpc": "2.0", "method": method, "params": params})

    def _request(
        self,
        process: subprocess.Popen[bytes],
        method: str,
        params: dict[str, Any],
        request_id: int,
    ) -> MCPResponse:
        self._send_message(process, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            message = self._read_message(process)
            if message.get("id") == request_id:
                if "error" in message:
                    raise ValueError(str(message["error"]))
                return MCPResponse(payload=message)

    @staticmethod
    def _send_message(process: subprocess.Popen[bytes], payload: dict[str, Any]) -> None:
        if process.stdin is None:
            raise ValueError("MCP stdin is unavailable.")
        body = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        process.stdin.write(header + body)
        process.stdin.flush()

    @staticmethod
    def _read_message(process: subprocess.Popen[bytes]) -> dict[str, Any]:
        if process.stdout is None:
            raise ValueError("MCP stdout is unavailable.")

        headers: dict[str, str] = {}
        while True:
            line = process.stdout.readline()
            if not line:
                stderr = b""
                if process.stderr is not None:
                    stderr = process.stderr.read() or b""
                raise ValueError(stderr.decode("utf-8", errors="ignore") or "MCP server closed unexpectedly.")
            if line in {b"\r\n", b"\n"}:
                break
            key, _, value = line.decode("utf-8").partition(":")
            headers[key.strip().lower()] = value.strip()

        content_length = int(headers.get("content-length", "0"))
        body = process.stdout.read(content_length)
        return json.loads(body.decode("utf-8"))
