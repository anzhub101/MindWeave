# MindWeave MVP Technical Summary

## 1. FoT Alignment

MindWeave is implemented as a compact, FoT-inspired reasoning runtime with a clear separation between static design artifacts, synthesized design artifacts, and live execution state.

- Requirements reference: [docs/requirements-planning.md](/Users/manzeem/MindWeave/docs/requirements-planning.md) is the converted Markdown source from the shared DOCX and is treated as the synthesis reference for generated programs.
- Design Plane: [backend/app/services/program_synthesizer.py](/Users/manzeem/MindWeave/backend/app/services/program_synthesizer.py) creates versioned reasoning-program bundles from the requirements reference plus the user prompt. Static examples and policy definitions still live in [backend/app/design_artifacts](/Users/manzeem/MindWeave/backend/app/design_artifacts).
- Runtime Plane: [backend/app/models/runtime.py](/Users/manzeem/MindWeave/backend/app/models/runtime.py), [backend/app/runtime/scheduler.py](/Users/manzeem/MindWeave/backend/app/runtime/scheduler.py), [backend/app/runtime/controller.py](/Users/manzeem/MindWeave/backend/app/runtime/controller.py), [backend/app/runtime/constraints.py](/Users/manzeem/MindWeave/backend/app/runtime/constraints.py), and [backend/app/runtime/budget.py](/Users/manzeem/MindWeave/backend/app/runtime/budget.py) implement the executable Graph Reasoning State, node orchestration, verify gates, and budgets.
- Knowledge Layer: [backend/app/services/document_processor.py](/Users/manzeem/MindWeave/backend/app/services/document_processor.py) and [backend/app/services/knowledge_base.py](/Users/manzeem/MindWeave/backend/app/services/knowledge_base.py) provide immutable document capture, extraction, chunking, and evidence retrieval. PostgreSQL persistence is modeled via SQLAlchemy in [backend/app/db/models.py](/Users/manzeem/MindWeave/backend/app/db/models.py), with `docker-compose.yml` prepared for a pgvector-capable Postgres deployment.

FoT distinguishes an execution graph from the reasoning graph. In the MVP:

- The execution graph is the task DAG made of `GraphNodeState` plus `GraphEdge`.
- The reasoning graph is captured as `ThoughtRecord` entries generated after each node, with explicit dependencies on prior thoughts.

This preserves both how the system executed and what intermediate reasoning artifacts were produced.

## 2. Requirements Mapping

The main MVP requirement groups are covered as follows.

- Prompt-to-Plan Engine: [backend/app/services/task_service.py](/Users/manzeem/MindWeave/backend/app/services/task_service.py) synthesizes a reasoning program from the requirements reference and the user prompt, then instantiates the resulting GRS.
- Scheduler and Controller: the controller executes one dependency-ready node at a time using the `priority_based` policy. This satisfies FR-SCH-01 through FR-CON-03 with deterministic ordering.
- Graph Mutation Safety and Neuro-Symbolic Control: [backend/app/runtime/constraints.py](/Users/manzeem/MindWeave/backend/app/runtime/constraints.py) enforces that guarded nodes cannot run until their verify nodes complete successfully. This is the MVP expression of the requested constraint injector.
- Budgets and Convergence: [backend/app/runtime/budget.py](/Users/manzeem/MindWeave/backend/app/runtime/budget.py) tracks node, token, and runtime consumption, while the controller halts cleanly when no further safe progress is possible.
- Persistence and Audit Trail: every run produces snapshots under `backend/data/snapshots/<task_id>/` and a final audit package under `backend/data/audit_packages/<task_id>.json`. Task runs are also persisted in the database table `task_runs`.
- Registries and Version History: [backend/app/services/artifact_registry_service.py](/Users/manzeem/MindWeave/backend/app/services/artifact_registry_service.py) persists programs, templates, policies, schemas, and evaluations as first-class versioned artifacts. Promotion history is recorded with justification and exposed through registry APIs.
- Output Validation: the final structured output is validated against the synthesized JSON Schema before the run is considered healthy.
- LLM Orchestration: [backend/app/services/llm_gateway.py](/Users/manzeem/MindWeave/backend/app/services/llm_gateway.py) uses K2 Think v2 via the agentic endpoint for program synthesis and node execution.
- Determinism, audit, and graph controls: [docs/determinism-audit-and-graph-controls.md](/Users/manzeem/MindWeave/docs/determinism-audit-and-graph-controls.md) records the implemented determinism modes, replay/diff support, evidence graph, graph patches, approval gates, and control-level behavior.

## 3. Domain Behavior

The system is no longer locked to a finance-specific operator. Instead:

1. the requirements Markdown provides the architectural contract
2. K2 Think v2 synthesizes a program bundle for the current task
3. the runtime executes each node generically using node instructions, dependency outputs, and retrieved evidence
4. a verify node must pass before guarded downstream nodes can execute
5. the final synthesis node produces schema-constrained structured output plus a UI summary card

The generic executor lives in [backend/app/services/generic_reasoning_operator.py](/Users/manzeem/MindWeave/backend/app/services/generic_reasoning_operator.py). The included financial audit sample pack remains useful as a demonstration domain, but it is no longer hardcoded into the orchestration path.

## 4. UI Mapping

The React UI is intentionally shaped around the supplied mockups and prompt notes.

- Shell and chrome: [frontend/src/App.tsx](/Users/manzeem/MindWeave/frontend/src/App.tsx), [frontend/src/components/Sidebar.tsx](/Users/manzeem/MindWeave/frontend/src/components/Sidebar.tsx), and [frontend/src/components/HeaderBar.tsx](/Users/manzeem/MindWeave/frontend/src/components/HeaderBar.tsx)
- Reasoning graph: [frontend/src/components/GraphCanvas.tsx](/Users/manzeem/MindWeave/frontend/src/components/GraphCanvas.tsx)
- Inspector drawer: [frontend/src/components/InspectorDrawer.tsx](/Users/manzeem/MindWeave/frontend/src/components/InspectorDrawer.tsx)
- Prompt and export panel: [frontend/src/components/PromptComposer.tsx](/Users/manzeem/MindWeave/frontend/src/components/PromptComposer.tsx) and [frontend/src/components/SummaryCard.tsx](/Users/manzeem/MindWeave/frontend/src/components/SummaryCard.tsx)

The styling follows the requested digital-noir, Nordic, low-color direction: monochrome surfaces, subtle parchment verification accents, a faint drafting grid, and restrained motion using Framer Motion.

## 5. Optimization Plane

The Optimization Plane is implemented as a benchmark-and-promotion loop rather than left as a placeholder.

- Experimentation: [backend/app/services/experiment_service.py](/Users/manzeem/MindWeave/backend/app/services/experiment_service.py) runs benchmark prompt sets and records accuracy, runtime, and token usage.
- Hyperparameter search: [backend/app/services/optimization_service.py](/Users/manzeem/MindWeave/backend/app/services/optimization_service.py) tunes instruction prefixes, policies, and evaluation profiles across candidate runs.
- Version promotion: the optimizer can promote the best-performing profile into the template registry with recorded justification and promotion history.

## 6. Remaining Product Constraints

- Exact graph-level determinism for external hosted LLMs remains best-effort. Deterministic mode still enforces `temperature=0`, fixed scheduler ordering, and seeded execution where supported, but hosted-model providers can still introduce nondeterministic variance outside the application boundary.
- Direct Supabase Postgres connectivity is optional in the current local environment. Supabase Storage and Chunkr OCR are live-verified, while ORM persistence continues to work against the configured local database path unless a reachable Postgres URL is supplied.

## 7. Operational Docs

- Runtime operations guide: [docs/runtime-operations-guide.md](/Users/manzeem/MindWeave/docs/runtime-operations-guide.md)
- Determinism, audit, and graph controls: [docs/determinism-audit-and-graph-controls.md](/Users/manzeem/MindWeave/docs/determinism-audit-and-graph-controls.md)
