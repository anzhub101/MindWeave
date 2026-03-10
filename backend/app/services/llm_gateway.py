from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.config import get_settings


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMRequest(BaseModel):
    task: str
    prompt: str
    context: dict[str, Any] = Field(default_factory=dict)
    system_prompt: str | None = None
    messages: list[LLMMessage] = Field(default_factory=list)
    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None
    determinism_mode: str | None = None
    model_id: str | None = None
    model_version: str | None = None
    agentic: bool = True
    max_tokens: int | None = None


class LLMResponse(BaseModel):
    provider: str
    model: str
    model_version: str = ""
    content: str
    prompt_tokens: int
    completion_tokens: int
    provider_fingerprint: str = ""
    endpoint: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request_params: dict[str, Any] = Field(default_factory=dict)
    request_payload: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class MockProvider:
    provider_name = "mock"
    model_name = "deterministic-template"

    def __init__(
        self,
        provider_name: str | None = None,
        model_name: str | None = None,
        model_version: str = "1.0.0",
        endpoint: str = "local://mock",
        fingerprint: str | None = None,
    ) -> None:
        self.provider_name = provider_name or self.provider_name
        self.model_name = model_name or self.model_name
        self.model_version = model_version
        self.endpoint = endpoint
        self.fingerprint = fingerprint or self._default_fingerprint()

    def _default_fingerprint(self) -> str:
        return hashlib.sha256(f"{self.provider_name}:{self.model_name}:{self.model_version}".encode("utf-8")).hexdigest()[:16]

    def generate(self, request: LLMRequest) -> LLMResponse:
        content = self._complete(request)
        prompt_tokens = max(1, len(request.prompt.split()))
        completion_tokens = max(1, len(content.split()))
        request_payload = {
            "model": request.model_id or self.model_name,
            "prompt": request.prompt,
            "system_prompt": request.system_prompt,
            "context": request.context,
            "messages": [message.model_dump() for message in request.messages],
            "temperature": request.temperature,
            "top_p": request.top_p,
            "seed": request.seed,
            "determinism_mode": request.determinism_mode,
            "max_tokens": request.max_tokens,
        }
        return LLMResponse(
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            provider_fingerprint=self.fingerprint,
            endpoint=self.endpoint,
            request_params={
                "temperature": request.temperature,
                "top_p": request.top_p,
                "seed": request.seed,
                "determinism_mode": request.determinism_mode,
            },
            request_payload=request_payload,
            raw={"task": request.task},
        )

    def _complete(self, request: LLMRequest) -> str:
        if request.task == "program_synthesis":
            prompt = str(request.context.get("user_prompt", "reasoning task"))
            slug = (
                prompt.lower()
                .replace("perform", "")
                .replace("create", "")
                .replace("generate", "")
                .strip()
                .replace(" ", "_")
            )
            program_id = f"{slug[:32] or 'generic_reasoning'}_v1"
            return json.dumps(
                {
                    "template_id": f"{program_id}_template",
                    "template_name": "Generated Reasoning Template",
                    "domain": "general reasoning",
                    "mapping_explanation": "Deterministic fallback synthesized a generic reasoning program from the prompt.",
                    "planner_trace": {
                        "summary": "Selected a scoped analysis graph with a verification branch before final synthesis.",
                        "graph_shape_reason": "A linear scope-to-evidence flow with an explicit verification gate keeps the graph auditable and bounded.",
                        "evidence_sources_available": [
                            {
                                "source_id": "requirements_reference",
                                "source_type": "requirements_reference",
                                "label": "Requirements Reference",
                                "detail": "Planning requirements used to shape the graph.",
                            }
                        ],
                        "web_fallback_used": False,
                        "web_search_queries": [],
                        "candidate_graph_operations": [
                            {
                                "operation": "linear_scope_mapping",
                                "disposition": "selected",
                                "rationale": "A scope node followed by evidence mapping keeps early context explicit.",
                            },
                            {
                                "operation": "branch_for_verification",
                                "disposition": "selected",
                                "rationale": "A verify branch was preserved before synthesis to enforce grounded outputs.",
                            },
                        ],
                        "node_decisions": [
                            {
                                "node_id": "scope_definition",
                                "action": "added",
                                "reason": "The graph needs a first-class scope node to restate the user objective.",
                            },
                            {
                                "node_id": "verification_gate",
                                "action": "branched",
                                "reason": "Verification was separated from analysis so synthesis can be explicitly guarded.",
                            },
                        ],
                        "confidence": 0.82,
                        "unresolved_gaps": [],
                    },
                    "program": {
                        "program_id": program_id,
                        "version": "1.0.0",
                        "template_id": f"{program_id}_template",
                        "domain": "general reasoning",
                        "goal": prompt,
                        "policy": "priority_based",
                        "budget": {
                            "max_nodes": 12,
                            "max_tokens": 18000,
                            "max_runtime_seconds": 240,
                        },
                        "convergence_rule": "no_pending_nodes",
                        "output_schema": f"{program_id}_output_schema_v1",
                        "deterministic_defaults": {
                            "temperature": 0,
                            "seed": request.seed if request.seed is not None else 42,
                        },
                        "metadata": {
                            "summary_guidance": {
                                "headline": "Primary conclusion",
                                "verdict": "Overall outcome",
                            }
                        },
                        "nodes": [
                            {
                                "id": "scope_definition",
                                "title": "Scope Definition",
                                "subtitle": "Clarify objective and constraints",
                                "operation_type": "generate",
                                "instruction": "Define the task scope, objective, and relevant document set.",
                                "success_criteria": [
                                    "Task objective restated",
                                    "Key constraints listed",
                                ],
                                "priority": 10,
                                "depends_on": [],
                                "next": ["evidence_mapping"],
                                "guarded_by": [],
                                "metadata": {"layout": {"column": 1, "row": 0}},
                            },
                            {
                                "id": "evidence_mapping",
                                "title": "Evidence Mapping",
                                "subtitle": "Identify relevant evidence",
                                "operation_type": "analyze",
                                "instruction": "Extract and organize the most relevant evidence from the uploaded documents.",
                                "success_criteria": [
                                    "Evidence references captured",
                                    "Data gaps noted",
                                ],
                                "priority": 20,
                                "depends_on": ["scope_definition"],
                                "next": ["analysis", "verification_gate"],
                                "guarded_by": [],
                                "metadata": {"layout": {"column": 1, "row": 1}},
                            },
                            {
                                "id": "analysis",
                                "title": "Core Analysis",
                                "subtitle": "Develop structured reasoning",
                                "operation_type": "analyze",
                                "instruction": "Analyze the evidence to produce the main findings for the task.",
                                "success_criteria": ["Findings listed", "Reasoning references evidence"],
                                "priority": 30,
                                "depends_on": ["evidence_mapping"],
                                "next": ["synthesis"],
                                "guarded_by": ["verification_gate"],
                                "metadata": {"layout": {"column": 0, "row": 2}},
                            },
                            {
                                "id": "verification_gate",
                                "title": "Verification Gate",
                                "subtitle": "Check evidence sufficiency",
                                "operation_type": "verify",
                                "instruction": "Verify whether the evidence and analysis are sufficient and internally consistent.",
                                "success_criteria": [
                                    "Verification status returned",
                                    "Checks explicitly listed",
                                ],
                                "priority": 40,
                                "depends_on": ["evidence_mapping"],
                                "next": ["synthesis"],
                                "guarded_by": [],
                                "metadata": {"layout": {"column": 2, "row": 2}},
                            },
                            {
                                "id": "synthesis",
                                "title": "Final Synthesis",
                                "subtitle": "Produce structured output",
                                "operation_type": "synthesize",
                                "instruction": "Produce the final structured answer, reasoning summary, and recommended next steps.",
                                "success_criteria": [
                                    "Output matches schema",
                                    "Summary card prepared",
                                ],
                                "priority": 50,
                                "depends_on": ["analysis", "verification_gate"],
                                "next": [],
                                "guarded_by": ["verification_gate"],
                                "metadata": {"layout": {"column": 1, "row": 3}},
                            },
                        ],
                    },
                    "output_schema_definition": {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "title": f"{program_id}_output_schema_v1",
                        "type": "object",
                        "required": [
                            "objective",
                            "conclusion",
                            "findings",
                            "evidence_sources",
                            "next_steps",
                        ],
                        "properties": {
                            "objective": {"type": "string"},
                            "conclusion": {"type": "string"},
                            "findings": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "finding_records": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                            "evidence_sources": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "next_steps": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "additionalProperties": True,
                    },
                }
            )

        if request.task == "node_execution":
            node_id = str(request.context.get("node_id", "node"))
            operation_type = str(request.context.get("operation_type", "analyze"))
            summary = f"Completed {node_id.replace('_', ' ')}."
            payload: dict[str, Any] = {
                "summary": summary,
                "reasoning": f"Reviewed the {operation_type} node, aligned it to the requested scope, and grounded the response in the retrieved evidence identifiers.",
                "output": {
                    "node": node_id,
                    "insight": f"Deterministic mock output for {operation_type}.",
                },
                "evidence_ids": request.context.get("available_evidence_ids", [])[:2],
            }
            if operation_type == "verify":
                payload["verification_status"] = "passed"
                payload["verification_checks"] = [
                    "Evidence was present.",
                    "Dependencies were structurally valid.",
                ]
            if request.context.get("is_final_node"):
                direct_evidence = [
                    {
                        "document_id": evidence_id,
                        "document_name": evidence_id,
                        "chunk_id": evidence_id,
                    }
                    for evidence_id in request.context.get("available_evidence_ids", [])[:1]
                ]
                payload["final_output"] = {
                    "objective": request.context.get("user_prompt", ""),
                    "conclusion": "Deterministic mock synthesis completed successfully.",
                    "findings": ["Mock finding one", "Mock finding two"],
                    "finding_records": [
                        {
                            "id": "finding_1",
                            "text": "Mock finding one",
                            "support_level": "direct" if direct_evidence else "unsupported",
                            "evidence_refs": direct_evidence,
                        },
                        {
                            "id": "finding_2",
                            "text": "Mock finding two",
                            "support_level": "inferred",
                            "evidence_refs": [],
                        },
                    ],
                    "evidence_sources": request.context.get("available_evidence_ids", [])[:3],
                    "next_steps": ["Review exported audit package."],
                }
                payload["final_summary"] = {
                    "headline": "Structured reasoning completed",
                    "verdict": "Ready for review",
                    "key_points": ["Program synthesized from requirements reference."],
                    "metrics": [
                        {"label": "Nodes", "value": str(request.context.get("node_count", 0))},
                        {"label": "Evidence", "value": str(len(request.context.get("available_evidence_ids", [])))},
                    ],
                }
            return json.dumps(payload)

        if request.task == "json_repair":
            raw = request.context.get("raw_text", "{}")
            return raw if isinstance(raw, str) else json.dumps(raw)

        if request.task == "skill_generation":
            user_prompt = str(request.context.get("user_prompt", "generated skill"))
            language = str(request.context.get("language", "python")).lower()
            entrypoint_filename = "main.js" if language in {"javascript", "js", "typescript", "ts"} else "main.py"
            if language in {"javascript", "js", "typescript", "ts"}:
                code = (
                    "const fs = require('fs');\n"
                    "const raw = fs.readFileSync(0, 'utf8').trim();\n"
                    "const payload = raw ? JSON.parse(raw) : {};\n"
                    "console.log(JSON.stringify({ status: 'ok', skill: 'generated', received: payload }));\n"
                )
            else:
                code = (
                    "import json\n"
                    "import sys\n\n"
                    "raw = sys.stdin.read().strip()\n"
                    "payload = json.loads(raw) if raw else {}\n"
                    "print(json.dumps({'status': 'ok', 'skill': 'generated', 'received': payload}))\n"
                )
            return json.dumps(
                {
                    "name": "Generated Skill",
                    "description": f"Skill generated for: {user_prompt[:80]}",
                    "language": language,
                    "skill_type": str(request.context.get("skill_type", "script")),
                    "entrypoint_filename": entrypoint_filename,
                    "code": code,
                    "test_input": json.dumps({"message": "hello"}),
                    "notes": ["Mock provider returned a deterministic skill scaffold."],
                }
            )

        if request.task == "node_chat":
            node_title = str(request.context.get("node_title", "node"))
            user_message = str(request.context.get("user_message", ""))
            tool_results = request.context.get("tool_results", [])
            tool_note = " Tool output was included." if tool_results else ""
            return (
                f"{node_title}: I grounded this reply in the current node state and linked evidence.{tool_note} "
                f"Question received: {user_message}"
            )

        return "Deterministic completion."


class OpenAIProvider:
    provider_name = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model_name = model

    def generate(self, request: LLMRequest) -> LLMResponse:
        user_text = request.prompt
        if request.context:
            user_text = f"{request.prompt}\n\nContext:\n{json.dumps(request.context, indent=2)}"
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        if request.messages:
            messages.extend([message.model_dump() for message in request.messages])
        else:
            messages.append({"role": "user", "content": user_text})

        params: dict[str, Any] = {
            "model": request.model_id or self.model_name,
            "temperature": request.temperature if request.temperature is not None else 0.0,
            "input": messages,
        }
        if request.top_p is not None:
            params["top_p"] = request.top_p
        response = self.client.responses.create(**params)
        content = response.output_text
        usage = response.usage
        raw = response.model_dump(mode="json")
        provider_fingerprint = str(raw.get("system_fingerprint") or self.model_name)
        return LLMResponse(
            provider=self.provider_name,
            model=request.model_id or self.model_name,
            model_version=request.model_version or request.model_id or self.model_name,
            content=content,
            prompt_tokens=usage.input_tokens,
            completion_tokens=usage.output_tokens,
            provider_fingerprint=provider_fingerprint,
            endpoint="openai://responses",
            request_params={
                "temperature": request.temperature,
                "top_p": request.top_p,
                "seed": request.seed,
                "determinism_mode": request.determinism_mode,
            },
            request_payload=params,
            raw=raw,
        )


class K2Provider:
    provider_name = "k2"

    def __init__(
        self,
        api_key: str,
        model: str,
        chat_url: str,
        agent_url: str,
        temperature: float,
        reasoning_effort: str,
        top_p: float,
    ) -> None:
        self.api_key = api_key
        self.model_name = model
        self.chat_url = chat_url
        self.agent_url = agent_url
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self.top_p = top_p

    def generate(self, request: LLMRequest) -> LLMResponse:
        messages = self._build_messages(request)
        temperature = request.temperature if request.temperature is not None else self.temperature
        payload: dict[str, Any] = {
            "model": request.model_id or self.model_name,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "top_p": request.top_p if request.top_p is not None else self.top_p,
            "chat_template_kwargs": {"reasoning_effort": self.reasoning_effort},
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.seed is not None:
            payload["seed"] = request.seed

        url = self.agent_url if request.agentic and self.agent_url else self.chat_url
        response = httpx.post(
            url,
            headers={
                "accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=90.0,
        )
        response.raise_for_status()
        data = response.json()
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        usage = data.get("usage", {})
        return LLMResponse(
            provider=self.provider_name,
            model=request.model_id or self.model_name,
            model_version=request.model_version or request.model_id or self.model_name,
            content=content,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            provider_fingerprint=str(data.get("system_fingerprint") or hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]),
            endpoint=url,
            request_params={
                "temperature": temperature,
                "top_p": payload["top_p"],
                "seed": request.seed,
                "determinism_mode": request.determinism_mode,
            },
            request_payload=payload,
            raw=data,
        )

    @staticmethod
    def _build_messages(request: LLMRequest) -> list[dict[str, str]]:
        if request.messages:
            return [message.model_dump() for message in request.messages]

        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        user_content = request.prompt
        if request.context:
            user_content = f"{request.prompt}\n\nContext:\n{json.dumps(request.context, indent=2)}"
        messages.append({"role": "user", "content": user_content})
        return messages


class LLMGateway:
    def __init__(self) -> None:
        self.settings = get_settings()
        settings = self.settings
        if settings.llm_provider == "k2" and settings.resolved_k2_api_key:
            self.provider = K2Provider(
                api_key=settings.resolved_k2_api_key,
                model=settings.k2_model,
                chat_url=settings.k2_chat_base_url,
                agent_url=settings.k2_agent_base_url,
                temperature=settings.k2_temperature,
                reasoning_effort=settings.k2_reasoning_effort,
                top_p=settings.k2_top_p,
            )
        elif settings.llm_provider == "openai" and settings.openai_api_key:
            self.provider = OpenAIProvider(settings.openai_api_key, settings.openai_model)
        else:
            self.provider = MockProvider()
        self.strict_provider = MockProvider(
            provider_name="local",
            model_name=settings.strict_local_model_id,
            model_version=settings.strict_local_model_version,
            endpoint=settings.strict_local_endpoint,
        )

    def generate(self, request: LLMRequest) -> LLMResponse:
        provider = self._provider_for(request)
        prepared_request = self._prepare_request(request, provider)
        return provider.generate(prepared_request)

    def describe_provider(self, determinism_mode: str | None = None) -> dict[str, Any]:
        provider = self.strict_provider if determinism_mode == "strict_deterministic" else self.provider
        if isinstance(provider, MockProvider):
            return {
                "provider": provider.provider_name,
                "model_id": provider.model_name,
                "model_version": provider.model_version,
                "provider_fingerprint": provider.fingerprint,
                "endpoint": provider.endpoint,
            }
        if isinstance(provider, OpenAIProvider):
            return {
                "provider": provider.provider_name,
                "model_id": provider.model_name,
                "model_version": provider.model_name,
                "provider_fingerprint": provider.model_name,
                "endpoint": "openai://responses",
            }
        return {
            "provider": provider.provider_name,
            "model_id": provider.model_name,
            "model_version": provider.model_name,
            "provider_fingerprint": hashlib.sha256(provider.chat_url.encode("utf-8")).hexdigest()[:16],
            "endpoint": provider.chat_url,
        }

    def _provider_for(self, request: LLMRequest):
        if request.determinism_mode == "strict_deterministic":
            return self.strict_provider
        return self.provider

    def _prepare_request(self, request: LLMRequest, provider) -> LLMRequest:
        payload = request.model_dump()
        mode = request.determinism_mode or "non_deterministic"
        if mode in {"best_effort_deterministic", "strict_deterministic"}:
            payload["temperature"] = 0.0
            payload["top_p"] = 1.0
            payload["seed"] = request.seed if request.seed is not None else self.settings.deterministic_seed
        if mode == "strict_deterministic":
            payload["model_id"] = self.settings.strict_local_model_id
            payload["model_version"] = self.settings.strict_local_model_version
        elif request.model_id is None:
            if isinstance(provider, MockProvider):
                payload["model_id"] = provider.model_name
                payload["model_version"] = provider.model_version
            else:
                payload["model_id"] = getattr(provider, "model_name", self.settings.k2_model)
                payload["model_version"] = getattr(provider, "model_name", self.settings.k2_model)
        return LLMRequest.model_validate(payload)
