# NexusGraph — Engineering Plan

> Status: living document. Updated at the end of each implementation phase.
> All domain data in this project is **synthetic** and generated with a fixed seed.
> No real patients, trials, companies or medical claims exist anywhere in this repository.

## 1. Goal

A portfolio-grade **GraphRAG + Knowledge Graph Agent**: an open-source system that answers
complex enterprise questions by deciding *which* data source to consult — RDF knowledge
graph (SPARQL), PostgreSQL structured data (SQL), vector/semantic document search, or a
combination — and returns grounded answers with machine-checkable citations and a full
observability trace.

It is explicitly **not**: a thin LangChain wrapper, a toy chatbot, or a vector-only RAG demo.

## 2. Architecture (target)

```
User ──► FastAPI (/v1/query, SSE streaming)
           │
           ▼
      Agent Orchestrator (explicit state machine)
           │
           ├─► Planner / Router ── decides: SPARQL | SQL | Vector | Entity | Document | Verify
           │      (LLM-based when configured; deterministic heuristic fallback)
           ▼
      Tool Registry (typed Pydantic I/O, per-run tool budget)
           ├── run_sparql()            ──► pyoxigraph RDF store (guarded, read-only)
           ├── query_structured_data() ──► PostgreSQL via SQLAlchemy (SELECT-only guard)
           ├── search_documents()      ──► vector store (pgvector | local numpy) + BM25 rerank
           ├── get_entity() / get_relationships()
           ├── retrieve_document()
           └── verify_claim()
           ▼
      Evidence Ledger (every tool result → Evidence objects with source_id/location)
           ▼
      Synthesizer (LLM | deterministic template composer in mock mode)
           ▼
      Citation Verifier (no evidence → "insufficient evidence" answer, never fabricated cites)
           ▼
      Grounded Response {answer, claims[], evidence[], tools_used, trace_id}
```

Storage: PostgreSQL (+pgvector, +traces) · pyoxigraph RDF store · Redis cache (optional,
in-memory fallback) · filesystem object-store abstraction for documents.

## 3. Key engineering decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Explicit orchestration, no LangGraph/LangChain.** The agent is a small, readable state machine (`agent/orchestrator.py`). | Reviewers must be able to understand routing/tool contracts from the repo. LangGraph adds indirection with no capability we need. |
| D2 | **pyoxigraph as the RDF engine** (Turtle + full SPARQL 1.1), not rdflib (slow/partial SPARQL) and not a hosted triple store for v1. | Spec preference; pure wheel, fast, file-backed persistence via Docker volume. |
| D3 | **Dual storage profiles.** `local` profile: SQLite + numpy vector store + in-memory RDF + in-memory cache — runs with zero services. `postgres` profile: PostgreSQL + pgvector + pyoxigraph dir + Redis. | Tests must run without Docker/paid APIs; CI uses real Postgres service. Same code paths, chosen by config. |
| D4 | **Deterministic hash-based embeddings** (feature hashing, dim 256) as the default embedding backend; OpenAI-compatible embedding endpoint optional via config. | Reproducible, offline, zero-cost tests. Real embeddings are a config change, not a code change. Documented as a quality limitation of the default. |
| D5 | **LLM adapter layer**: `mock` (scripted, deterministic) and `openai-compatible` (any vendor/local via base_url). Token usage + cost accounting in both. | Vendor-neutral per spec; mock enables hermetic tests + hermetic evals. |
| D6 | **All generated SPARQL/SQL is untrusted.** SQL guard: AST-level SELECT-only check, denylist, timeout, row/byte limits, read-only DB user. SPARQL guard: query-form allowlist (SELECT/ASK only), operation/keyword denylist, timeout, result limits. | Spec security requirement; details in `docs/THREAT_MODEL.md`. |
| D7 | **Sync core, async edge.** Tools/stores are sync; FastAPI runs handlers in the threadpool; SSE streaming uses a sync generator. | SQLAlchemy, pyoxigraph, numpy are sync; avoids async-splattered code for no concurrency win at this scale. |
| D8 | **Traces stored in the app DB** (`/v1/traces/{id}` works out of the box) *and* exported via OTLP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. | Observability must work without running a collector; OTel SDK is still the span model. |
| D9 | **Evals are deterministic-first**: exact/golden graders + containment checks; LLM-as-judge is an optional secondary pass. `evals/run.py` writes `results.json` + `report.md`. README shows `NOT YET MEASURED` until a run is committed. | Spec requirement; prevents benchmark theatre. |
| D10 | **Provenance on every derived artifact**: chunks, extracted entities, triples, and claims carry `source_id` (+ location + extraction method). | Core GraphRAG requirement; enforced by tests. |
| D11 | **uv** for env/dependency management; **ruff + mypy** gates in CI. | Spec stack. |

## 4. Milestones (phases)

| Phase | Deliverable | Done when |
|-------|-------------|-----------|
| 0 | Repo scaffold, PLAN.md, uv project, license, git | `uv sync` resolves; `git init` clean |
| 1 | Config, structured logging, domain models, trace recorder | unit tests for config/models/tracing |
| 2 | `src/nexusgraph/synth/` generator + `ontology/nexusgraph.ttl` | generator reproducible (fixed seed), snapshot tests, ontology parses |
| 3 | Graph store (pyoxigraph), SPARQL guard, seed→RDF loader | guarded SPARQL tests pass; injection attempts rejected |
| 4 | Vector store (local+pgvector), document store, chunking, BM25 rerank | retrieval tests; hybrid ranking sanity |
| 5 | SQL layer (SQLAlchemy models), sqlguard, schema bootstrap | sqlguard tests; SQLite + Postgres parity |
| 6 | LLM adapters (mock/openai-compatible), usage/cost accounting | deterministic mock completions; usage recorded |
| 7 | Ingestion pipeline (CSV/JSON/MD/TXT/PDF → chunks/entities/triples/embeddings/provenance) | end-to-end ingest test; provenance asserted |
| 8 | Tools: search_documents, run_sparql, query_structured_data, get_entity, get_relationships, retrieve_document, verify_claim | tool contract tests (typed I/O, limits) |
| 9 | Orchestrator + planner/router + synthesizer + citation verifier | routing tests (semantic/graph/quant/mixed/unanswerable); citation tests |
| 10 | FastAPI app (query+SSE, entities, documents, traces, health/ready) + minimal UI | API integration tests; UI serves; trace inspectable |
| 11 | MCP server (stdio + HTTP mount), read-only, bounded | MCP tool list/call tests |
| 12 | Eval framework + dataset (incl. unanswerable + injection) + real mock-mode run | `python -m evals.run` produces results.json + report.md |
| 13 | Test suite green: unit + integration (postgres in CI) + security | `pytest` passes locally (local profile) and in CI (postgres profile) |
| 14 | Docs: README, ARCHITECTURE, THREAT_MODEL, EVALS, ONTOLOGY, SECURITY/CONTRIBUTING, Dockerfile, compose, CI, Makefile, .env.example | docs complete; no fake numbers |
| 15 | Final verification pass; PLAN.md closed out | all DoD checkboxes demonstrable |

## 5. Dependency graph (build order)

```
config/models ─► stores(graph/vector/sql) ─► tools ─► orchestrator ─► API ─► UI
      │                ▲                        ▲            ▲
      └── synth data ──┘        llm adapters ───┘   evals ───┘ (uses API-level components directly)
observability spans everything; ingestion bridges synth data → all stores; MCP wraps tools.
```

## 6. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Docker unavailable on dev machine → cannot verify compose locally | Local profile is the default dev path; compose validated via `docker compose config` in CI + Postgres-profile integration tests in CI services |
| Scope explosion (UI, MCP, PDF…) | Timeboxes: UI is one static page; PDF parse = pypdf text extraction only; MCP = tool re-exposure, no new logic |
| Mock mode too artificial → reviewers distrust | Mock LLM is documented as a *deterministic test double*; real-LLM path is first-class config; evals in mock mode labeled as such, never presented as LLM benchmarks |
| pgvector/SQLite behavioural drift | Store interfaces tested against both profiles; CI matrix runs integration suite on Postgres |
| Prompt-injection in corpus looks like real medical advice | All synthetic docs carry "SYNTHETIC" banners; adversarial fixtures live in eval dataset only, clearly labeled |
| Windows dev quirks (paths, signals) | Pure-Python local profile; no POSIX-only code in package (uvicorn/uv handle Windows) |

## 7. Out of scope (v1, documented in README roadmap)

Multi-tenant authn/authz (single-tenant with API key), write-back agent actions,
distributed deployment, GraphQL façade, streaming graph updates, real biomedical vocabularies
(SNOMED/LOINC licensing not redistributable — hence synthetic ontology).

---
## Phase log (updated at end of each phase)
- 2026-10-02 — Phase 0 complete: scaffold, plan, uv project, license, git repo.
