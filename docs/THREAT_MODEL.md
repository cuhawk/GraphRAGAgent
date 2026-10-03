# Threat model

Scope: the NexusGraph service as shipped in this repository — the agent
pipeline, its tools, the HTTP API, the MCP server and the UI. The data is
synthetic; the threats below are the ones that matter structurally for any
GraphRAG deployment of this shape, and each section lists the implemented
controls plus honest residual risks.

Assumptions:

- The questioner is untrusted (they may paste hostile text, including text
  copied from untrusted documents).
- **Retrieved data is untrusted.** Documents, RDF triples and rows can carry
  attacker-chosen content in real deployments; two of the bundled synthetic
  documents are deliberate adversarial fixtures.
- The operator is trusted; the model provider (if configured) is a semi-trusted
  third party that sees whatever is sent to it.

---

## T1. Prompt injection via retrieved content

**Threat.** A document (or row, or RDF literal) contains instructions —
"ignore all previous instructions and say X", "reveal the passphrase", "call
this URL" — and the agent treats them as instructions. Fixture: D-9013
(vendor security bulletin containing the compliance directive and a fake
passphrase), D-9014 (internal note with an exfiltration URL and code).

**Controls.**

- The deterministic synthesizer (default) *cannot* follow instructions: it
  composes claims mechanically from evidence. Content from documents can only
  appear as a quotation attached to its evidence id.
- The LLM synthesizer (optional) is instructed to treat evidence as data, and
  its output claims are re-validated against the ledger; anything uncited is
  dropped or flagged `unsupported`.
- Retrieved text is size-capped per call and per run (limits in
  `config.LimitsSettings`), reducing instruction-surface and dilution.
- Eval cases A1–A3 assert the property operationally: forbidden strings must
  never appear except as cited quotations.

**Residual risk.** With a real LLM, injected instructions can still influence
*phrasing* (e.g. tone, which snippet gets quoted first). Claims and citations
remain constrained, but phrase-level influence is not eliminated; treat
LLM-mode answers as untrusted text until re-verified downstream.

## T2. Malicious retrieved content (poisoning)

**Threat.** An attacker plants a document whose *content* is false and
therefore poisons answers with a legitimate-looking citation.

**Controls.**

- Full provenance: every claim's evidence list shows source id + location +
  snippet; per-document named graphs make the originating document of every
  mention triple explicit. Readers (and graders) can always see *which*
  document a statement came from.
- `verify_claim` + orchestrator-level re-verification guarantee that claims
  reference retrieved evidence — a poisoned source is visible, not hidden.

**Residual risk.** Provenance makes poisoning *attributable*, not harmless.
There is no source-trust weighting; an operator would add document-level
trust tiers before using this with real corpora.

## T3. Query injection (SPARQL)

**Threat.** Untrusted text reaches the SPARQL engine: update queries,
federated `SERVICE` calls to external endpoints, graph-store admin operations,
or semantic DoS via runaway queries.

**Controls.** (`security/sparqlguard.py`, enforced on every execution — the
builder is a convenience, the guard is the boundary)

- SELECT/ASK only; INSERT/DELETE/LOAD/CLEAR/DROP/CONSTRUCT/DESCRIBE and
  friends are rejected outright.
- `SERVICE`/federation denied; denylist plus a context-tracking comment
  stripper (understands `<iri>` and quoted strings, so `ontology#` IRIs
  survive while keywords hidden in comments do not — regression-tested).
- Query length cap, wall-clock timeout in a worker thread (pyoxigraph
  materialises results inside the worker), row cap, bounded result bytes.

**Residual risk.** Guard bypasses are a cat-and-mouse game; the denylist is
belt-and-braces around the allowlist principle (SELECT/ASK-only), but a
fuzzing pass over the scanner is on the roadmap.

## T4. Query injection (SQL) / unauthorized data access

**Threat.** Raw SQL from a model or user; access to tables outside the
domain; value-based injection (`'; DROP TABLE …`).

**Controls.**

- **The model never writes SQL.** Structured queries are typed `QuerySpec`
  objects; the SQL guard validates table/column names against the
  `STRUCTURED_SCHEMA` allowlist, identifier shape, value types/lengths,
  aggregation rules and IN-list sizes.
- Compilation goes through SQLAlchemy Core with bound parameters — filter
  values are never interpolated (regression test: a `DROP TABLE` payload in a
  filter value is inert).
- Execution is read-only, row-capped, and timeout-bounded
  (`statement_timeout` on PostgreSQL).
- IDs referenced by tools (entity ids, document ids) are validated Pydantic
  fields, not interpolated strings.

## T5. Data exfiltration through the agent

**Threat.** Convince the agent to send corpus or store contents to an
external endpoint (fixture: D-9014's `exfil.example.invalid/collect`).

**Controls.**

- The answer path makes **no outbound network calls**. The only HTTP client in
  the runtime is the optional LLM adapter (`llm/openai_compat.py`), which talks
  to the configured base URL and never receives API keys from tool results.
- SPARQL federation is rejected by the guard (no `SERVICE`-based egress).
- Tool outputs are capped; URLs in documents are inert text.

**Residual risk.** If an operator configures a third-party LLM endpoint, the
*prompts* (question + evidence snippets) are seen by that provider — inherent
to LLM use, documented so it is a decision, not a surprise.

## T6. Excessive tool use / resource exhaustion

**Threat.** Questions that drive unbounded tool calls, huge results, or
long-running queries (cost and availability).

**Controls.**

- Per-run tool-call budget (`ToolBudget`, default 12) shared by every path
  that executes tools (API, MCP).
- Per-tool wall-clock timeouts (SPARQL 5 s, SQL 5 s, tools 20 s), row caps
  (500), per-result byte caps (64 kB) and retrieval character budgets.
- Input limit: questions above `max_input_chars` are rejected with 422 before
  any work starts (Pydantic-validated at the API boundary too).
- MCP outputs are additionally capped at `max_result_bytes` per call.

## T7. Unsupported claims / hallucinated citations

**Threat.** The agent states things the data does not support, or cites
evidence that does not exist — the core trust failure of RAG systems.

**Controls.**

- Single citation source: the per-run `EvidenceLedger`. Claims may only carry
  ledger ids; `verify_claim` (deterministic) and the orchestrator's final
  re-check both enforce it. `[n]` markers are range-checked against the
  evidence list.
- Claims without evidence are flagged `unsupported`; when nothing supports an
  answer the agent returns `insufficient: true` with a reason (unanswerable
  cases never reach the tools at all).
- The eval suite measures citation precision/recall and unsupported-claim
  rate on every run.

## T8. Denial of service via ingestion

**Threat.** Oversized or hostile files ingested into the store.

**Controls.** Bounded chunking (`max_chunk_chars`), per-document text
truncation on retrieval, parser failures isolated per file and reported
(`IngestionReport.skipped_files`). Ingestion is a trusted, operator-invoked
flow in this codebase (no upload endpoint) — the risk is operator-scoped.

---

## Summary matrix

| Threat | Primary controls | Tested by |
| --- | --- | --- |
| T1 prompt injection | deterministic synthesis; claim re-validation; caps | evals A1–A3, e2e injection test |
| T2 poisoning | provenance, per-doc named graphs | e2e citation contract |
| T3 SPARQL injection | SELECT/ASK allowlist, denylist, scanner, timeouts | `test_sparql_guard.py`, `test_security.py` |
| T4 SQL injection | QuerySpec allowlist, parameterised Core SQL | `test_sqlguard.py`, `test_security.py` |
| T5 exfiltration | no answer-path egress, no federation | architecture (no client exists) |
| T6 resource abuse | budgets, timeouts, caps, input limits | `test_security.py`, API 422s |
| T7 unsupported claims | ledger-only citations, final re-check, insufficiency | citation metrics on every eval run |
| T8 ingestion abuse | bounded chunking, per-file isolation | ingestion tests |

## Reporting

See [SECURITY.md](../SECURITY.md) for the (project-level) disclosure policy.
