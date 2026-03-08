from __future__ import annotations

import hashlib
import json
import platform
import sys
from typing import Any

from app.core.config import Settings
from app.models.runtime import GraphReasoningState, PromptTrace


NON_DETERMINISTIC_KEYS = {
    "timestamp",
    "created_at",
    "started_at",
    "completed_at",
    "latency_ms",
    "graph_build_ms",
    "scheduler_metrics_ms",
    "runtime_seconds",
    "tokens_used",
    "last_used_at",
    "task_id",
    "replay_of_task_id",
    "replay_source_snapshot_label",
    "trace_id",
    "cache_hit",
    "logs",
    "grs_hash",
    "reproducibility_hash",
    "storage_path",
    "text_path",
    "local_storage_path",
    "local_text_path",
    "cache_stats",
}


def stable_hash(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def prompt_hash(
    prompt: str,
    system_prompt: str | None = None,
    context: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> str:
    return stable_hash(
        {
            "prompt": prompt,
            "system_prompt": system_prompt or "",
            "context": context or {},
            "params": params or {},
        }
    )


def build_execution_env_hash(
    settings: Settings,
    determinism_mode: str,
    provider_metadata: dict[str, Any],
) -> str:
    return stable_hash(
        {
            "python_version": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "determinism_mode": determinism_mode,
            "provider_metadata": provider_metadata,
            "strict_local_model_id": settings.strict_local_model_id,
            "strict_local_model_version": settings.strict_local_model_version,
            "strict_inference_engine_version": settings.strict_inference_engine_version,
            "strict_cuda_stack": settings.strict_cuda_stack,
            "strict_instance_type": settings.strict_instance_type,
            "strict_disable_dynamic_batching": settings.strict_disable_dynamic_batching,
            "strict_parallelism": settings.strict_parallelism,
        }
    )


def canonicalize_for_hashing(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key in NON_DETERMINISTIC_KEYS:
                continue
            normalized[key] = canonicalize_for_hashing(item)
        return normalized
    if isinstance(value, list):
        return [canonicalize_for_hashing(item) for item in value]
    return value


def grs_hash(state: GraphReasoningState) -> str:
    return stable_hash(canonicalize_for_hashing(state.model_dump(mode="json")))


def reproducibility_hash(
    state: GraphReasoningState,
    provider_metadata: dict[str, Any],
) -> str:
    effective_seed = None
    if state.prompt_traces:
        effective_seed = state.prompt_traces[-1].params.get("seed")
    if effective_seed is None and isinstance(state.program_blueprint, dict):
        deterministic_defaults = state.program_blueprint.get("deterministic_defaults", {})
        if isinstance(deterministic_defaults, dict):
            effective_seed = deterministic_defaults.get("seed")

    return stable_hash(
        {
            "prompt_hash": state.prompt_hash,
            "grs_hash": state.grs_hash,
            "determinism_mode": state.determinism_mode.value,
            "control_level": state.control_level.value,
            "model_id": state.model_id,
            "model_version": state.model_version,
            "provider_fingerprint": state.provider_fingerprint,
            "seed": effective_seed,
            "execution_env_hash": state.execution_env_hash,
            "program_blueprint": canonicalize_for_hashing(state.program_blueprint or {}),
            "output_schema_definition": canonicalize_for_hashing(state.output_schema_definition or {}),
            "provider_metadata": provider_metadata,
        }
    )


def trace_from_request_response(
    trace_id: str,
    phase: str,
    node_id: str | None,
    prompt: str,
    system_prompt: str | None,
    context: dict[str, Any],
    params: dict[str, Any],
    provider: str,
    model_id: str,
    model_version: str,
    provider_fingerprint: str,
    endpoint: str | None,
    request_payload: dict[str, Any] | None = None,
    response_payload: dict[str, Any] | None = None,
) -> PromptTrace:
    normalized_request_payload = request_payload or {}
    normalized_response_payload = response_payload or {}
    return PromptTrace(
        trace_id=trace_id,
        phase=phase,
        node_id=node_id,
        prompt=prompt,
        system_prompt=system_prompt,
        context=context,
        params=params,
        request_payload=normalized_request_payload,
        response_payload=normalized_response_payload,
        provider=provider,
        model_id=model_id,
        model_version=model_version,
        provider_fingerprint=provider_fingerprint,
        endpoint=endpoint,
        prompt_hash=prompt_hash(prompt=prompt, system_prompt=system_prompt, context=context, params=params),
        response_hash=stable_hash(normalized_response_payload),
    )
