# MindWeave

MindWeave is a FoT-inspired Reasoning-as-a-Service platform that synthesizes reasoning programs from the platform requirements reference plus the user prompt. The repository includes:

- A FastAPI backend that generates a domain-specific reasoning program at runtime, executes it generically, and persists the full Graph Reasoning State
- A React/TypeScript/Tailwind frontend shaped to match the supplied dark enterprise mockups
- An immutable audit package export containing source documents, the synthesized program blueprint, verification logs, and final structured output
- An optional Pinecone-backed retrieval path for real vector search with integrated embeddings
- A bundled `Invisium FY2026` sample document pack for repeatable end-to-end runs

## What This Demonstrates

- Prompt-to-plan synthesis onto a versioned reasoning program
- Static design-plane artifacts separated from live runtime state
- Requirements-driven schema and graph generation
- Priority-based scheduling with verify-gate enforcement
- K2 Think v2 acting as the orchestrator/controller model through `/v1/chat/completions`
- Optional Pinecone retrieval with a dedicated namespace per task
- Full traceability of node inputs, outputs, verification results, generated schemas, and exported audit JSON
- Versioned design artifacts with promotion history and optimizer-selected profiles

## Repository Layout

```text
backend/
  app/
    api/                 FastAPI routes
    core/                Settings
    db/                  SQLAlchemy models and session
    design_artifacts/    Static examples, policies, templates, schemas
    models/              Artifact, runtime, and API models
    runtime/             Scheduler, controller, constraints, budgets, audit snapshots
    services/            Document ingestion, program synthesis, knowledge retrieval, LLM gateway, generic node executor
  scripts/               Repeatable end-to-end runner
  tests/                 Basic runtime and flow tests
frontend/
  src/
    components/          Dashboard shell, graph canvas, inspector drawer, prompt composer
sample_data/
  invisium_fy2026/       Deterministic demo document pack
docs/
  requirements-planning.md
  technical-summary.md
```

## Backend Setup

1. Create a virtual environment.
2. Install the backend package.
3. Run the API server.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e backend
uvicorn app.main:app --reload --app-dir backend
```

The backend defaults to SQLite for zero-friction local setup:

```env
MW_DATABASE_URL=sqlite:///./mindweave.db
MW_LLM_PROVIDER=k2
MW_K2_API_KEY=your_key_here
MW_K2_MODEL=MBZUAI-IFM/K2-Think-v2
MW_K2_CHAT_BASE_URL=https://api.k2think.ai/v1/chat/completions
MW_K2_AGENT_BASE_URL=https://api.k2think.ai/v1/chat/completions
MW_VECTOR_BACKEND=local
```

To use PostgreSQL instead, start the bundled pgvector-capable container and point `MW_DATABASE_URL` at it:

```bash
docker compose up -d
```

Example database URL:

```env
MW_DATABASE_URL=postgresql+psycopg://mindweave:mindweave@localhost:5432/mindweave
```

## Pinecone Setup

MindWeave supports two retrieval backends:

- `MW_VECTOR_BACKEND=local`: local deterministic hashing plus SQL persistence
- `MW_VECTOR_BACKEND=pinecone`: Pinecone integrated embeddings with per-task namespaces

To enable Pinecone:

```env
MW_VECTOR_BACKEND=pinecone
MW_PINECONE_API_KEY=your_key_here
MW_PINECONE_INDEX_NAME=mindweave-knowledge
MW_PINECONE_CLOUD=aws
MW_PINECONE_REGION=us-east-1
MW_PINECONE_EMBED_MODEL=llama-text-embed-v2
MW_PINECONE_TEXT_FIELD=chunk_text
MW_PINECONE_NAMESPACE_PREFIX=task_
MW_PINECONE_AUTO_CREATE_INDEX=true
MW_PINECONE_CONSISTENCY_WAIT_SECONDS=10
```

The backend creates or reuses the configured Pinecone index, writes document chunks as text records, and searches them using integrated embeddings. Namespaces are mandatory in the Pinecone path and are derived from the task id.

To verify the Pinecone connection without starting the whole app:

```bash
source .venv/bin/activate
MW_VECTOR_BACKEND=pinecone MW_PINECONE_API_KEY=your_key_here python backend/scripts/pinecone_smoke_test.py
```

## Supabase Storage and Database

MindWeave now supports Supabase as the infrastructure layer for object storage and database connection derivation.

Storage configuration:

```env
MW_STORAGE_BACKEND=supabase
MW_SUPABASE_URL=https://your-project.supabase.co
MW_SUPABASE_SECRET_KEY=your_secret_key
MW_SUPABASE_PUBLISHABLE_KEY=your_publishable_key
MW_SUPABASE_UPLOADS_BUCKET=mindweave-documents
MW_SUPABASE_AUDIT_BUCKET=mindweave-audits
```

When `MW_STORAGE_BACKEND=supabase`, uploaded source documents, extracted text artifacts, snapshots, and audit packages are written to Supabase Storage and mirrored locally under `backend/data/`.

Database configuration:

```env
MW_SUPABASE_URL=https://your-project.supabase.co
MW_SUPABASE_DB_PASSWORD=your_db_password
```

If `MW_DATABASE_URL` is not set explicitly, the backend derives a direct Postgres URL from the Supabase project ref and DB password. If your environment cannot reach the direct `db.<project-ref>.supabase.co` host, set `MW_DATABASE_URL` explicitly to the pooled connection string from the Supabase dashboard instead.

If you paste a raw Postgres URL from a dashboard, use the actual password value without square brackets and URL-encode special characters such as `@` as `%40`.

## Design Registry APIs

The design plane is exposed through versioned registry APIs:

- `GET /api/design/{kind}` lists programs, policies, templates, schemas, or evaluations
- `POST /api/design/{kind}` creates or updates a versioned artifact
- `POST /api/design/{kind}/{artifact_id}/promote` records a promotion justification and marks the promoted version
- `GET /api/design/{kind}/{artifact_id}/versions` returns the version history for an artifact
- `GET /api/design/{kind}/{artifact_id}/promotions` returns promotion history with recorded justifications

Supported `kind` values are `program`, `policy`, `template`, `schema`, and `evaluation`.

## Chunkr OCR

Chunkr is supported as an OCR fallback for PDFs with poor embedded text extraction.

```env
MW_CHUNKR_API_KEY=your_chunkr_key
MW_CHUNKR_ENABLE_PDF_OCR_FALLBACK=true
MW_CHUNKR_PDF_CHAR_THRESHOLD=120
MW_CHUNKR_OCR_STRATEGY=Auto
```

If a PDF yields less than the configured text threshold through `pypdf`, MindWeave automatically sends the file to Chunkr and uses the returned markdown as the extracted text.

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

The frontend expects the API at `http://localhost:8000/api` by default. Override with `VITE_API_BASE_URL` if needed.

## Running the Demo

1. Start the backend.
2. Start the frontend.
3. Open the dashboard.
4. Submit a task prompt. If you do not upload files, the bundled sample pack is used.
5. The backend synthesizes a reasoning program from [docs/requirements-planning.md](/Users/manzeem/MindWeave/docs/requirements-planning.md) and the prompt.
6. Uploaded documents are stored through the configured storage backend, OCR-processed when needed, and chunked for retrieval.
7. Inspect nodes in the graph.
8. Export the audit package from the result card.

If no backend is reachable, the frontend falls back to a polished offline demo state so the UI can still be reviewed.

## Running a Direct End-to-End Check

```bash
source .venv/bin/activate
python backend/scripts/run_e2e.py
```

This performs:

- program synthesis from the requirements markdown
- document ingestion from the sample pack
- generic node execution through the runtime
- retrieval through the configured vector backend
- final export persistence into `backend/data/`
- registry persistence for generated programs, templates, and node/program schemas
- schema validation logging for node inputs and node outputs

## LLM Provider Behavior

K2 Think v2 is the primary orchestrator/controller model for the app. The backend uses:

- `https://api.k2think.ai/v1/chat/completions`
- model `MBZUAI-IFM/K2-Think-v2`
- default temperature `0.8`

The project still ships with a mock provider fallback so the runtime can be exercised without external credentials.

Optional OpenAI mode:

```env
MW_LLM_PROVIDER=openai
MW_OPENAI_API_KEY=your_key_here
MW_OPENAI_MODEL=gpt-4.1-mini
```

The provider abstraction lives in [backend/app/services/llm_gateway.py](/Users/manzeem/MindWeave/backend/app/services/llm_gateway.py).

## Verification and Auditability

- Every node execution produces a log entry.
- Every verify node emits verification checks.
- Snapshots are written during execution and on completion.
- Final output is validated against a JSON Schema.
- The audit export includes source documents, GRS state, verification logs, and final output.

## Tests

Once dependencies are installed:

```bash
cd backend
pytest
```

The current tests cover verify-gate enforcement, product-readiness features, and the Pinecone vector-store path.

## Important Files

- Requirements reference: [docs/requirements-planning.md](/Users/manzeem/MindWeave/docs/requirements-planning.md)
- Coverage matrix: [docs/requirements-coverage.md](/Users/manzeem/MindWeave/docs/requirements-coverage.md)
- Program synthesis: [backend/app/services/program_synthesizer.py](/Users/manzeem/MindWeave/backend/app/services/program_synthesizer.py)
- Runtime state models: [backend/app/models/runtime.py](/Users/manzeem/MindWeave/backend/app/models/runtime.py)
- Controller: [backend/app/runtime/controller.py](/Users/manzeem/MindWeave/backend/app/runtime/controller.py)
- Generic node executor: [backend/app/services/generic_reasoning_operator.py](/Users/manzeem/MindWeave/backend/app/services/generic_reasoning_operator.py)
- Vector store abstraction: [backend/app/services/vector_store.py](/Users/manzeem/MindWeave/backend/app/services/vector_store.py)
- Pinecone smoke test: [backend/scripts/pinecone_smoke_test.py](/Users/manzeem/MindWeave/backend/scripts/pinecone_smoke_test.py)
- Frontend dashboard: [frontend/src/App.tsx](/Users/manzeem/MindWeave/frontend/src/App.tsx)
- Technical mapping: [docs/technical-summary.md](/Users/manzeem/MindWeave/docs/technical-summary.md)
