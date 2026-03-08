# K2 Think Best-Effort Determinism Guide

Imported from `/Users/manzeem/Downloads/Untitled document.md` on 2026-03-08 so the implementation source used for this change is stored in-repo.

## Goal

Implement best-effort deterministic execution for MindWeave using the K2 Think v2 API so task runs support:

- auditable reasoning runs
- reproducibility tracking
- drift detection
- compliance logging

This is best-effort determinism, not strict bit-identical reproducibility.

## Actionable Steps

1. Enforce deterministic decoding parameters centrally in `llm_gateway.py`.
   - `temperature = 0`
   - `top_p = 1`
   - `seed = 42`
2. Make the deterministic gateway path the default executor for reasoning nodes in best-effort mode.
3. Persist execution metadata for each reasoning node and task run:
   - `model_id`
   - `model_version`
   - `temperature`
   - `top_p`
   - `seed`
   - `timestamp`
   - `request_payload`
   - `response_payload`
   - `prompt_hash`
   - `response_hash`
   - `grs_hash`
   - `execution_env_hash`
4. Compute and store a `prompt_hash`.
5. Compute and store a `grs_hash`.
6. Compute and store an `execution_env_hash`.
7. Compute and store a run-level `reproducibility_hash`.
8. On rerun, compare the new reproducibility hash with the original run and log determinism variance if they differ.
9. Ensure each node execution:
   - sends a deterministic request
   - logs prompt metadata
   - stores the response
   - updates the reasoning graph
   - computes hashes

## Limitations

Hosted best-effort determinism can still vary because of:

- provider model updates
- infrastructure changes
- batching variability
- hardware differences

Strict reproducibility requires a pinned local model stack.

## Determinism Modes

- `best_effort_deterministic`: current implementation using hosted model controls
- `strict_deterministic`: future-facing local pinned stack

## Acceptance Criteria

Deterministic execution is implemented when:

- identical tasks produce the same GRS hash at least 80% of the time
- all metadata fields are recorded
- the reproducibility hash is stored
- determinism drift is detectable
