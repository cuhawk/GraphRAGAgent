# Architecture

This document explains how NexusGraph is put together and why. It is the
companion to the module docstrings; where they disagree, the code wins and
this file should be fixed.

## 1. Bird's-eye view

```
                ┌────────────────────────────────────────────┐
   HTTP / SSE   │ FastAPI  (api/app.py + static/index.html)  │
   MCP stdio    │ MCP server (mcp_server/server.py)          │
   CLI          │ cli.py (bootstrap / serve / mcp / status)  │
                └───────────────────┬────────────────────────┘
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │  AgentOrchestrator    │   agent/orchestrator.py
                        │  (one run = 1 trace)  │
                        └──┬──────┬──────┬──────┘
              resolve      │      │      │  synthesize
              entities     │      │      │  (deterministic or LLM)
                           ▼      ▼      ▼
                Planner   Guarded tools   EvidenceLedger
        agent/planner.py  tools/*         agent/evidence.py
                           │
      ┌────────────┬───────┴────────┬───────────────┐
      ▼            ▼                ▼               ▼
 GraphStore   StructuredQuery  RetrievalService  DocumentStore
 (pyoxigraph) (SQLAlchemy      (embeddings +     EntityStore
 store/graph  Core, allowlist) BM25 hybrid)      TraceSqlSink
      ▼            ▼                ▼               ▼
   RDF file    SQLite or         numpy /          SQL tables
   + named     PostgreSQL        pgvector         + traces
   graphs      + pgvector        (+ Redis cache)
```

## 2. Composition root

`runtime.py` builds a `Runtime` dataclass once per process: settings, engine,
graph store, entity/document stores, vector index, embedder, retrieval
service, trace sink, tracer, cache. Everything above (API, CLI, MCP, evals,
tests) consumes the same bundle — there is no second wiring path.

`bootstrap()` generates the synthetic dataset and ingests it; it is idempotent
(structured tables are cleared before insert; the RDF store directory is
rebuilt when the dataset is regenerated).

## 3. The agent path (one run)

1. **Resolve entities** — `QuestionEntityResolver` matches question surface
   forms against canonical entity names + corpus aliases (longest-first,
   overlap-suppressing). This grounds "Site A" → `site:S-1001`.
2. **Plan** — `HeuristicRouter` maps keyword/intent signals to 1–4 tool steps
   carrying *intents* (`site_trends`, `products_of_delayed_trials`, `search`,
   …) and entity hints. `LLMPlanner` (when a real model is configured) asks
   the model to choose from the registry and validates every field; any
   deviation falls back to the heuristic router.
3. **Execute** — the orchestrator expands intents into guarded arguments:
   SPARQL templates (`sparql_templates.py`), typed QuerySpecs
   (`query_specs.py`), retrieval args. Each step runs inside a trace span,
   acquires the shared `ToolBudget`, and its typed result is converted to
   ledger evidence. Errors are captured per step (a failing tool never kills
   the run).
4. **Synthesize** — `DeterministicSynthesizer` builds claims from the
   structured series (least-squares slopes → trend claims), SPARQL bindings,
   document snippets and cross-source id overlaps; no model in the loop.
   `LLMSynthesizer` (optional) writes the answer from the evidence JSON; its
   claims are filtered to ledger-known evidence ids and any failure falls back
   to the deterministic path.
5. **Verify & return** — every claim's evidence ids are re-checked against the
   ledger, `[n]` markers in the answer text are range-checked, and the answer
   is returned with the full evidence list, tool runs, plan rationale,
   `trace_id`, usage and latency.

### Why intents instead of raw queries

The planner cannot produce an unguarded query *by construction*: it picks
among builders whose output is parameterised and whose arguments come from
validated Pydantic models. The SPARQL/SQL guards remain the enforcement point
(defence in depth — the orchestrator may also execute model-proposed SPARQL in
LLM mode, which then must pass the same guard).

## 4. Storage profiles

| Concern | `local` (default) | `postgres` |
| --- | --- | --- |
| Relational | SQLite file | PostgreSQL |
| Vectors | numpy `LocalVectorIndex` (eager refresh, cosine) | pgvector `<=>` cosine |
| RDF | pyoxigraph file store | pyoxigraph file store (same) |
| Cache | in-memory TTL | Redis (graceful degradation) |
| Timeouts | wall-clock thread budget | + `SET LOCAL statement_timeout` |

`Settings.profile` selects the wiring; components are identical otherwise.

## 5. Ingestion pipeline

`parse → chunk (≤800 chars, paragraph-preserving) → extract entities
(deterministic regex + ID-token validation against known corpus ids; optional
LLM-assisted extractor) → resolve/dedupe (normalized-name keys; aliases.json)
→ embed (deterministic hashing embedder by default, dim 256) → vector index →
RDF: per-document named graph with `rdf:type ResearchDocument` +
`DOCUMENT_MENTIONS` triples → structured CSVs into the typed schema
(→ regional analytics marts) → manifest with expected facts.

Every derived artifact carries provenance: chunks reference `document_id`,
RDF mention triples live in the document's named graph, entity/relationship
rows carry `source_ids`.

## 6. Embeddings & retrieval

The default `hash` embedder is deterministic feature hashing (blake2b over
word tokens + character trigrams, L2-normalised, dim 256) — no model, no
network, reproducible tests. `openai-compatible` embedding providers plug in
via `make_embedder`. `RetrievalService` fuses dense cosine (0.65) with BM25
rerank (0.35), applies chunk filters and enforces a per-call character budget.

## 7. Observability

`TraceRecorder` collects a span tree per run and persists it through
`TraceSqlSink` (`/v1/traces/{id}` is authoritative, collector-free). When
`NEXUSGRAPH_OTLP_ENDPOINT` is set, spans are mirrored to OpenTelemetry with
the nexusgraph trace id attached; bridge failures are swallowed. Logs are
structured (JSON optional), and LLM usage is accumulated per run.

## 8. Decision log (abbreviated)

- **D1: no agent framework.** The orchestration loop is ~300 lines of
  explicit Python; a state-machine library would hide the part this project is
  about.
- **D2: pyoxigraph** for RDF/SPARQL — in-process, fast, real SPARQL 1.1
  (rdflib is the portable fallback, not bundled).
- **D3: dual profiles, one code path** — the local profile makes tests hermetic
  and cheap; the postgres profile proves the production wiring.
- **D4: hash embeddings by default** — reproducible, dependency-free,
  honest about being lexical-ish; semantic quality comes from the pluggable
  real embedder, which is *not* measured by the committed eval numbers.
- **D5: vendor-neutral LLM** — a single OpenAI-compatible adapter + a
  scripted mock for tests; no provider SDKs in the dependency tree.
- **D6: untrusted query path** — guards are the boundary; builders are just
  convenience.
- **D7: synchronous core** — the agent path is sync and CPU/IO-bound locally;
  the API streams progress from a worker thread rather than making the whole
  core async.
- **D8: app-local traces authoritative**, OTel optional.
- **D9: deterministic-first evals** — graders are mechanical; an LLM judge
  would make scores non-reproducible and the numbers unverifiable.
- **D10: provenance everywhere** — if a derived artifact cannot say where it
  came from, it is a bug.

## 9. Known limitations

- Cross-region *comparative* questions ("which region…") answer only for
  groups whose rows made it into the evidence cap; per-region phrasing gets a
  scoped, fully-cited answer.
- The RDF store remains file-backed in both profiles; a triple store service
  (e.g. Oxigraph server) is a straightforward swap behind `GraphStore`.
- `LocalVectorIndex` holds all chunk embeddings in memory (fine at corpus
  scale; pgvector takes over for larger corpora).
- The UI is intentionally minimal (single file, no build step).
