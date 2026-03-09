# Determinism, Audit, and Graph Controls

This document records the backend work implemented for the following runtime-control tasks:

1. best-effort and strict deterministic execution
2. graph replay and diff
3. stricter evidence traceability
4. explicit execution, thought, and evidence graphs
5. human-editable graph patch requests
6. controlled node-level delegation
7. explicit expansion contracts
8. reasoning visibility tiers
9. approval gates for high-stakes nodes
10. run classification and control levels

The implementation is centered in:

- `backend/app/services/task_service.py`
- `backend/app/services/llm_gateway.py`
- `backend/app/services/generic_reasoning_operator.py`
- `backend/app/models/runtime.py`
- `backend/app/api/routes.py`

## 1. Deterministic Execution

### Best-effort deterministic

Implemented behavior:

- forces `temperature=0`
- forces `top_p=1`
- applies a fixed seed where the provider surface supports it
- records `model_id`, `model_version`, `provider_fingerprint`, `execution_endpoint`
- logs prompt traces with full prompt, system prompt, context, request params, provider metadata, and prompt hash
- computes and stores:
  - `prompt_hash`
  - `grs_hash`
  - `execution_env_hash`
  - `reproducibility_hash`

Primary runtime fields on `GraphReasoningState`:

- `determinism_mode`
- `model_id`
- `model_version`
- `provider_fingerprint`
- `execution_endpoint`
- `prompt_hash`
- `grs_hash`
- `execution_env_hash`
- `reproducibility_hash`

Prompt traces now also record:

- `request_payload`
- `response_payload`
- `response_hash`

### Strict deterministic

Implemented behavior:

- routes execution through the strict local provider path
- pins strict-local runtime metadata from settings:
  - local model id
  - local model version
  - inference engine version
  - CUDA stack
  - instance type
  - dynamic batching disabled flag
  - parallelism
- includes those values in `execution_env_hash`

Current limitation:

- the repo now has the strict deterministic contract and routing surface, but it still uses a local deterministic provider abstraction rather than a real production-pinned checkpoint and inference stack.

## 2. Replay and Diff

Replay support is implemented through snapshot or stored-run re-execution.

Capabilities:

- replay latest persisted run state
- replay a named snapshot
- replay from a clean reset state
- resume directly from a stored snapshot state

Diff support compares two runs and returns:

- changed nodes
- changed prompts
- changed evidence
- changed model metadata
- changed final output

Primary API paths:

- `POST /api/tasks/{task_id}/replay`
- `POST /api/tasks/diff`

Primary code:

- `backend/app/services/task_service.py`
- `backend/app/runtime/audit.py`

## 3. Evidence Traceability

Evidence capture is stricter than the earlier MVP shape.

Each evidence reference can now store:

- `document_id`
- `document_name`
- `chunk_id`
- `page`
- `char_start`
- `char_end`
- `retrieval_score`
- `support_level`
- `citation_mode`
- `source_type`
- `text_excerpt`

Final findings are normalized into `finding_records`, each with:

- `id`
- `text`
- `support_level`
- `evidence_refs`

Validation rule:

- a final finding may not be unlabeled and unsupported
- if it has no linked evidence, it must be explicitly marked as `inferred`, `unsupported`, or `user_provided`

Primary code:

- `backend/app/services/knowledge_base.py`
- `backend/app/services/generic_reasoning_operator.py`
- `backend/app/services/task_service.py`

## 4. Three Explicit Graphs

The runtime now separates three graph concepts:

### Execution graph

- stored as `nodes`, `edges`, and `execution_sequence`
- answers what ran and in what order

### Thought graph

- stored as `ThoughtRecord` entries with dependencies on prior thoughts
- answers which intermediate reasoning artifacts were produced

### Evidence graph

- stored as `evidence_graph_nodes` and `evidence_graph_edges`
- answers which claims and findings depend on which evidence references

Evidence graph node kinds currently include:

- `claim`
- `finding`
- `evidence`

## 5. Graph Patch Requests

Graph patching is implemented as a structured runtime feature rather than prompt-only mutation.

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

Patch record fields:

- `patch_type`
- `target_node_id`
- `change_reason`
- `requested_by`
- `approved_by`
- `payload`
- `resulting_program_version`
- `auto_rerun`
- `applied_at`

Primary API path:

- `POST /api/tasks/{task_id}/patch`

Primary code:

- `backend/app/services/graph_patch_service.py`
- `backend/app/services/task_service.py`

Natural-language planning now sits on top of the patch engine; see [docs/nl-graph-planner-implementation.md](/Users/manzeem/MindWeave/docs/nl-graph-planner-implementation.md).

## 6. Node-Level Delegation

Delegation is implemented as a controlled node property, not unrestricted free-form spawning.

Each node can now specify:

- `executor_type`
- `max_child_agents`
- `max_recursion_depth`
- `required_approvals`
- `expansion_contracts`

Supported executor types:

- `llm_operator`
- `tool_operator`
- `agent_operator`
- `human_operator`

Delegation constraints currently enforced:

- delegation only occurs for `agent_operator` nodes
- delegation is blocked if child-agent budget is zero
- delegation is blocked if the node budget is already exhausted
- delegation respects per-node child-agent limits
- delegation respects recursion-depth limits
- delegated nodes carry metadata tying them back to the parent node

Current limitation:

- delegation policy is runtime-controlled and auditable, but still conservative; it does not yet implement a richer policy language for complexity scoring and summarization quality.

## 7. Expansion Contracts

Nodes can define `expansion_contracts` so deeper reasoning is explicit and reviewable.

Examples supported by the model:

- `expand_summary`
- `expand_evidence`
- `expand_alternatives`
- `expand_counterarguments`
- `expand_calculations`
- `expand_subgraph`

These contracts are stored on the node and surfaced through graph patches and reasoning traces.

## 8. Reasoning Visibility Tiers

The API exposes structured reasoning visibility tiers rather than raw unrestricted internal reasoning dumps.

Supported tiers:

- `summary_trace`
- `structured_reasoning_trace`
- `expanded_analytic_trace`

Tier behavior:

- `summary_trace`: node identity, status, evidence used, conclusion
- `structured_reasoning_trace`: adds node input, node output, verification, score, prompt hash
- `expanded_analytic_trace`: adds thought summary, expansion contracts, delegation metadata, model metadata

Control-level caps:

- `strict_audit` is capped to `summary_trace`
- `regulated` is capped at `structured_reasoning_trace`

Primary API path:

- `GET /api/tasks/{task_id}/trace?tier=...`

## 9. Approval Gates

Approval gating is now explicit in the runtime.

Node-level control:

- `required_approvals`
- `requires_human_review` in node metadata

Behavior:

- high-stakes nodes can require approval before execution continues
- `strict_audit` can force dual approval on flagged high-stakes nodes
- review decisions are appended to immutable runtime history and also stored in persistent review records

Examples of high-stakes triggers in the current implementation:

- synthesis nodes
- nodes whose title, subtitle, or instruction mentions audit opinion, fraud, material weakness, or regulatory non-compliance

Primary code:

- `backend/app/runtime/controller.py`
- `backend/app/services/task_service.py`

## 10. Control Levels

Every run can now declare a control level:

- `exploratory`
- `operational`
- `regulated`
- `strict_audit`

These levels drive:

- determinism defaults
- approval defaults
- reasoning visibility defaults
- whether strict deterministic mode is forced
- logging and audit strictness

Current behavior:

- `exploratory`: expanded trace allowed, non-deterministic by default
- `operational`: best-effort deterministic by default
- `regulated`: best-effort deterministic plus approval restrictions
- `strict_audit`: strict deterministic forced, summary-only trace exposure, stronger approval requirements

## Verification

The implementation is covered by:

- `backend/tests/test_runtime_flow.py`
- `backend/tests/test_product_readiness.py`
- `backend/tests/test_determinism_and_audit_controls.py`

Latest validation run:

```bash
./.venv/bin/pytest backend/tests -q
```

Expected result at time of writing:

```text
22 passed
```
