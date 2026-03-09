# Runtime Operations Guide

This guide documents the backend task operations added for deterministic runs, replay, diff, graph patching, and structured reasoning trace access.

## Execute a Task

Endpoint:

```text
POST /api/tasks/execute
```

Form fields:

- `prompt`
- `deterministic`
- `determinism_mode`
- `control_level`
- `auto_approve_human_review`
- `use_sample_data`
- `files`

Important enums:

- `determinism_mode`
  - `non_deterministic`
  - `best_effort_deterministic`
  - `strict_deterministic`
- `control_level`
  - `exploratory`
  - `operational`
  - `regulated`
  - `strict_audit`

Returned run metadata now includes:

- `determinism_mode`
- `control_level`
- `default_visibility_tier`
- `model_id`
- `model_version`
- `provider_fingerprint`
- `execution_endpoint`
- `prompt_hash`
- `grs_hash`
- `execution_env_hash`
- `reproducibility_hash`
- `execution_sequence`
- `evidence_graph_nodes`
- `evidence_graph_edges`
- `prompt_traces`
- `graph_patch_history`

## Replay a Run

Endpoint:

```text
POST /api/tasks/{task_id}/replay
```

Request body:

```json
{
  "snapshot_label": "final",
  "resume_from_snapshot": false,
  "auto_approve_human_review": false
}
```

Behavior:

- if `snapshot_label` is omitted, the service replays from the stored task snapshot
- if `resume_from_snapshot=true`, replay starts from the stored intermediate state
- otherwise, the run is reset and executed again from a clean task state

## Diff Two Runs

Endpoint:

```text
POST /api/tasks/diff
```

Request body:

```json
{
  "left_task_id": "task_a",
  "right_task_id": "task_b"
}
```

Minimum diff output groups:

- `changed_nodes`
- `changed_prompts`
- `changed_evidence`
- `changed_model_metadata`
- `changed_final_output`

`changed_nodes` captures:

- node id
- changed field list
- left and right statuses
- left and right prompt hashes
- left and right outputs

## Apply a Graph Patch

Endpoint:

```text
POST /api/tasks/{task_id}/patch
```

Request body shape:

```json
{
  "patch_type": "change_policy",
  "target_node_id": null,
  "change_reason": "Use breadth-first ordering for review.",
  "requested_by": "qa",
  "approved_by": "lead",
  "payload": {
    "policy": "breadth_first"
  },
  "auto_rerun": false
}
```

Supported patch types:

- `add_node`
- `remove_node`
- `rewire_dependency`
- `rerun_subtree`
- `change_policy`
- `change_budget`
- `change_evidence_scope`
- `change_executor`
- `expand_node`

Examples:

### Re-run one analysis branch

```json
{
  "patch_type": "rerun_subtree",
  "target_node_id": "revenue_analysis",
  "change_reason": "Re-check revenue branch only.",
  "requested_by": "user",
  "approved_by": "reviewer",
  "payload": {},
  "auto_rerun": true
}
```

### Add a fraud review branch

```json
{
  "patch_type": "add_node",
  "target_node_id": "controls_review",
  "change_reason": "Add a fraud-focused branch.",
  "requested_by": "user",
  "approved_by": "reviewer",
  "payload": {
    "id": "fraud_review",
    "title": "Fraud Review",
    "subtitle": "Assess fraud indicators",
    "operation_type": "analyze",
    "instruction": "Review transactions for fraud indicators and summarize material findings.",
    "depends_on": ["controls_review"],
    "next_nodes": ["verification_gate"],
    "priority": 35,
    "expansion_contracts": ["expand_evidence", "expand_counterarguments"]
  },
  "auto_rerun": true
}
```

### Ignore vendor payments under 10k

```json
{
  "patch_type": "change_evidence_scope",
  "target_node_id": "vendor_payments_review",
  "change_reason": "Exclude low-value vendor payments.",
  "requested_by": "user",
  "approved_by": "reviewer",
  "payload": {
    "instruction_note": "Ignore vendor payments below 10000 unless already flagged for fraud or compliance risk."
  },
  "auto_rerun": true
}
```

## Plan a Natural-Language Change

Endpoint:

```text
POST /api/tasks/{task_id}/plan-change
```

Request body shape:

```json
{
  "request_text": "Expand the fraud branch and assign a forensic agent",
  "requested_by": "qa-reviewer",
  "selected_node_id": "analysis"
}
```

Response groups:

- `status`
- `intent`
- `proposal`
- `validation`
- `target_node_resolution`
- `clarification_question`

Possible statuses:

- `proposed`
- `invalid`
- `needs_clarification`

If the planner cannot safely resolve the target node, it returns `needs_clarification` instead of a patch proposal.

## Apply a Planned Change

Endpoint:

```text
POST /api/tasks/{task_id}/apply-planned-change
```

Request body shape:

```json
{
  "proposal_id": "proposal_ab12cd34",
  "approved_by": "audit-lead",
  "approval_notes": "Approved for rerun.",
  "auto_rerun": true
}
```

Behavior:

- only validated proposals can be applied
- `regulated` and `strict_audit` tasks require approval
- high-risk proposals also require approval
- application flows through the structured graph patch engine rather than mutating the graph directly from NL

## Retrieve a Structured Reasoning Trace

Endpoint:

```text
GET /api/tasks/{task_id}/trace?tier=summary_trace
```

Supported tiers:

- `summary_trace`
- `structured_reasoning_trace`
- `expanded_analytic_trace`

Notes:

- `strict_audit` runs are capped to `summary_trace`
- `regulated` runs are capped to `structured_reasoning_trace`

## Snapshot and Audit Storage

Snapshots are written under:

```text
backend/data/snapshots/<task_id>/
```

Audit packages are written under:

```text
backend/data/audit_packages/<task_id>.json
```

The audit package includes:

- source documents
- final output
- final summary
- full GRS snapshot
- verification logs
- review history
- evaluation logs
- schema validation logs
- event log
- change intents
- patch proposals
- patch validation history

## Evidence Model

Each node can return evidence references with:

- document id
- document name
- chunk id
- page
- char span
- retrieval score
- support level
- citation mode
- source type
- text excerpt

Final findings are stored as `finding_records` and should be linked to evidence. If evidence is unavailable, the finding must be labeled as:

- `inferred`
- `unsupported`
- `user_provided`

## Control-Level Defaults

### Exploratory

- default determinism: `non_deterministic`
- default visibility: `expanded_analytic_trace`

### Operational

- default determinism: `best_effort_deterministic`
- default visibility: `structured_reasoning_trace`

### Regulated

- default determinism: `best_effort_deterministic`
- visibility capped to `structured_reasoning_trace`
- stronger approval behavior

### Strict Audit

- forced determinism: `strict_deterministic`
- visibility capped to `summary_trace`
- stronger approval behavior, including dual-approval support on flagged nodes

## Tests

Relevant tests:

- `backend/tests/test_runtime_flow.py`
- `backend/tests/test_product_readiness.py`
- `backend/tests/test_determinism_and_audit_controls.py`

Run:

```bash
./.venv/bin/pytest backend/tests -q
```
