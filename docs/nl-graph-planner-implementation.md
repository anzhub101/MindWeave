# NL Graph Planner Implementation

This document records the work implemented from [docs/NL_graph_planner.md](/Users/manzeem/MindWeave/docs/NL_graph_planner.md).

The planner adds a safe natural-language layer on top of the structured graph patch engine. Natural language produces a proposal, not a direct graph mutation.

## Summary

Implemented planner flow:

1. natural-language request
2. node resolution
3. structured change intent
4. structured patch proposal
5. validation
6. approval-aware apply flow
7. audit persistence

Primary backend entry points:

- [backend/app/services/task_service.py](/Users/manzeem/MindWeave/backend/app/services/task_service.py)
- [backend/app/api/routes.py](/Users/manzeem/MindWeave/backend/app/api/routes.py)
- [backend/app/change_planning](/Users/manzeem/MindWeave/backend/app/change_planning)

## Implemented Modules

The planner package lives in [backend/app/change_planning](/Users/manzeem/MindWeave/backend/app/change_planning).

Modules:

- [intent_models.py](/Users/manzeem/MindWeave/backend/app/change_planning/intent_models.py)
  - `ChangeIntent`
  - `NodeResolutionResult`
  - `PlannedPatchOperation`
  - `PatchProposal`
  - `PatchValidationResult`
- [node_resolver.py](/Users/manzeem/MindWeave/backend/app/change_planning/node_resolver.py)
  - resolves user language to node ids using aliases, title matching, and fuzzy scoring
- [intent_parser.py](/Users/manzeem/MindWeave/backend/app/change_planning/intent_parser.py)
  - classifies request type and extracts payload fields
- [patch_planner.py](/Users/manzeem/MindWeave/backend/app/change_planning/patch_planner.py)
  - converts a `ChangeIntent` into one or more structured patch operations
- [proposal_explainer.py](/Users/manzeem/MindWeave/backend/app/change_planning/proposal_explainer.py)
  - generates reviewer-facing patch explanations
- [validation_bridge.py](/Users/manzeem/MindWeave/backend/app/change_planning/validation_bridge.py)
  - simulates proposals against graph safety rules before application

## Supported Intent Types

The parser currently supports:

- `expand_node`
- `rerun_subtree`
- `add_node`
- `remove_node`
- `change_policy`
- `change_budget`
- `change_evidence_scope`
- `change_executor`
- `rewire_dependency`

Examples the parser is designed to handle:

- “Expand the fraud branch”
- “Re-run only the revenue analysis”
- “Add an internal controls review node”
- “Exclude vendor payments under 10k”
- “Use a forensic agent on this node”

## Planner Output

The planner produces three explicit objects:

- `ChangeIntent`
  - parsed request classification and normalized payload
- `PatchProposal`
  - one or more structured patch operations plus summary, explanation, risk, and approval requirement
- `PatchValidationResult`
  - validation status, warnings, errors, and affected nodes

These objects are persisted on the task state in [backend/app/models/runtime.py](/Users/manzeem/MindWeave/backend/app/models/runtime.py):

- `change_intents`
- `patch_proposals`
- `patch_validation_history`

## Validation Rules

Validation is implemented in [backend/app/change_planning/validation_bridge.py](/Users/manzeem/MindWeave/backend/app/change_planning/validation_bridge.py).

Implemented checks:

- no cycles created
- verify gates preserved for synthesis paths
- connected path to synthesis nodes remains intact
- graph stays within `max_nodes`
- expansion contracts are in the allowed set
- executor changes are checked against control level
- high-risk proposals are marked as approval-requiring

Validation works by simulating the proposal against a cloned graph state through the existing patch engine in [backend/app/services/graph_patch_service.py](/Users/manzeem/MindWeave/backend/app/services/graph_patch_service.py).

## API Endpoints

The planner is exposed through [backend/app/api/routes.py](/Users/manzeem/MindWeave/backend/app/api/routes.py).

### Plan a change

```text
POST /api/tasks/{task_id}/plan-change
```

Request fields:

- `request_text`
- `requested_by`
- `selected_node_id`

Response fields:

- `status`
- `intent`
- `proposal`
- `validation`
- `target_node_resolution`
- `clarification_question`

### Apply a planned change

```text
POST /api/tasks/{task_id}/apply-planned-change
```

Request fields:

- `proposal_id`
- `approved_by`
- `approval_notes`
- `auto_rerun`

Only validated proposals can be applied. Approval is enforced for regulated and strict-audit control levels and for proposals marked as approval-requiring.

## Runtime Integration

Planner application is integrated into [backend/app/services/task_service.py](/Users/manzeem/MindWeave/backend/app/services/task_service.py).

Implemented behavior:

- proposals are generated without mutating the live graph
- proposals are logged into the task event log
- clarification requests are returned instead of unsafe proposals
- validated proposals are applied through the existing graph patch engine
- applied proposals can trigger reruns of the affected scope
- planner activity is included in the audit package

Planner audit events include:

- `nl_change_requested`
- `nl_change_clarification_required`
- `nl_patch_proposed`
- `nl_patch_applied`

## Frontend Flow

The task-view planner UI is implemented in [frontend/src/components/ChangePlannerPanel.tsx](/Users/manzeem/MindWeave/frontend/src/components/ChangePlannerPanel.tsx) and wired through [frontend/src/App.tsx](/Users/manzeem/MindWeave/frontend/src/App.tsx).

The UI currently supports:

- entering a natural-language change request
- sending the selected node id as context
- previewing parsed intent
- previewing patch operations and explanation
- showing validation warnings and errors
- capturing approver id when required
- applying the validated proposal

Frontend API bindings live in [frontend/src/api.ts](/Users/manzeem/MindWeave/frontend/src/api.ts).

## Tests

Planner coverage is in [backend/tests/test_nl_graph_planner.py](/Users/manzeem/MindWeave/backend/tests/test_nl_graph_planner.py).

The tests verify:

- valid executor-change planning and audit persistence
- clarification flow for ambiguous node references
- approval enforcement for strict-audit tasks
- add-node proposal creation and application

## Current Limitations

- Node resolution is alias-and-fuzzy-match based. It does not yet use embeddings or semantic retrieval.
- The parser is rule-based rather than LLM-based, which keeps planning deterministic but limits language coverage.
- Clarification is returned as a response payload. There is no dedicated multi-turn planner session model yet.
- The planner works best for the supported request categories; broader workflow refactoring still requires explicit structured patches.
