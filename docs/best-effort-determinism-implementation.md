# Best-Effort Determinism Implementation

This document records the work implemented from [docs/k2-think-best-effort-determinism-guide.md](/Users/manzeem/MindWeave/docs/k2-think-best-effort-determinism-guide.md).

The goal of the work was to make hosted-model execution auditable and reproducible on a best-effort basis without claiming strict bit-identical replay.

## Scope

Implemented scope:

- centralized deterministic decoding controls
- run-level determinism metadata
- prompt and response trace capture
- reproducibility hashing
- replay-time variance detection

Out of scope for this implementation:

- true local strict reproducibility with pinned checkpoint, CUDA stack, and inference engine
- provider-side guarantees beyond what the hosted K2 API exposes

## Runtime Behavior

When `determinism_mode=best_effort_deterministic`, the runtime now enforces the following centrally in [backend/app/services/llm_gateway.py](/Users/manzeem/MindWeave/backend/app/services/llm_gateway.py):

- `temperature=0`
- `top_p=1`
- `seed=42` when no explicit seed is provided
- model id and model version capture
- provider fingerprint and endpoint capture

The K2 HTTP request is issued through [backend/app/services/llm_gateway.py](/Users/manzeem/MindWeave/backend/app/services/llm_gateway.py) and the provider configuration defaults live in [backend/app/core/config.py](/Users/manzeem/MindWeave/backend/app/core/config.py).

## Captured Metadata

Every run now records determinism metadata on `GraphReasoningState` in [backend/app/models/runtime.py](/Users/manzeem/MindWeave/backend/app/models/runtime.py):

- `determinism_mode`
- `model_id`
- `model_version`
- `provider_fingerprint`
- `execution_endpoint`
- `prompt_hash`
- `grs_hash`
- `execution_env_hash`
- `reproducibility_hash`

Every prompt trace now records:

- full prompt
- system prompt
- structured context
- request params
- request payload
- response payload
- provider metadata
- `prompt_hash`
- `response_hash`

The prompt trace model is also defined in [backend/app/models/runtime.py](/Users/manzeem/MindWeave/backend/app/models/runtime.py).

## Hash Pipeline

The determinism hash helpers are implemented in [backend/app/services/runtime_metadata.py](/Users/manzeem/MindWeave/backend/app/services/runtime_metadata.py).

Implemented hashes:

- `prompt_hash`
  - stable hash of prompt, system prompt, context, and params
- `grs_hash`
  - stable hash of the Graph Reasoning State after removing runtime-only noise such as task ids, timestamps, cache-hit flags, and event logs
- `execution_env_hash`
  - stable hash of runtime environment and provider metadata
- `reproducibility_hash`
  - stable hash of prompt hash, graph hash, seed, determinism mode, model metadata, and execution environment metadata

This design was necessary so repeated best-effort deterministic runs can compare meaningfully even when ephemeral runtime bookkeeping differs.

## Active K2 Call Sites

Best-effort determinism is applied across every K2 call that goes through `LLMGateway`:

- program synthesis in [backend/app/services/program_synthesizer.py](/Users/manzeem/MindWeave/backend/app/services/program_synthesizer.py)
- synthesis JSON repair in [backend/app/services/program_synthesizer.py](/Users/manzeem/MindWeave/backend/app/services/program_synthesizer.py)
- node execution in [backend/app/services/generic_reasoning_operator.py](/Users/manzeem/MindWeave/backend/app/services/generic_reasoning_operator.py)
- node JSON repair in [backend/app/services/generic_reasoning_operator.py](/Users/manzeem/MindWeave/backend/app/services/generic_reasoning_operator.py)
- optional LLM-based evaluation in [backend/app/services/evaluation_service.py](/Users/manzeem/MindWeave/backend/app/services/evaluation_service.py)

## Replay and Drift Detection

Replay support already existed, but determinism work added replay-time variance detection in [backend/app/services/task_service.py](/Users/manzeem/MindWeave/backend/app/services/task_service.py).

On replay, the runtime now:

1. recomputes `grs_hash`
2. recomputes `reproducibility_hash`
3. compares the new reproducibility hash against the source run
4. emits one of these audit events:
   - `determinism_replay_matched`
   - `determinism_variance_detected`

This makes provider drift, graph drift, and prompt mutations visible in the audit trail.

## API Surface

Best-effort determinism is controlled from `POST /api/tasks/execute` in [backend/app/api/routes.py](/Users/manzeem/MindWeave/backend/app/api/routes.py).

Relevant request fields:

- `deterministic`
- `determinism_mode`
- `control_level`

Relevant response fields:

- `determinism_mode`
- `model_id`
- `model_version`
- `provider_fingerprint`
- `execution_endpoint`
- `prompt_hash`
- `grs_hash`
- `execution_env_hash`
- `reproducibility_hash`
- `prompt_traces`

## Tests

Coverage for the implemented behavior is in [backend/tests/test_determinism_and_audit_controls.py](/Users/manzeem/MindWeave/backend/tests/test_determinism_and_audit_controls.py).

The tests verify:

- determinism metadata is present on task runs
- prompt traces include request payload, response payload, and response hash
- repeated best-effort deterministic runs produce stable graph and reproducibility hashes
- replay logs determinism variance when provider metadata changes

## Current Limitations

- Hosted K2 execution is still best-effort only. Provider-side updates and infrastructure changes can still cause variance.
- `strict_deterministic` is implemented as a backend contract and routing surface, but the repo still uses a local deterministic provider abstraction rather than a production-pinned local model stack.
