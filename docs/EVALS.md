# Evaluations

How NexusGraph is measured. The guiding rule: **every published number comes
from an executed run recorded in `evals/results/`**; anything not measured is
labelled as such rather than estimated.

## Running

```bash
uv run python -m evals.run                 # full suite (19 cases)
uv run python -m evals.run --cases R1,S1   # subset by id
uv run python -m evals.run --limit 5       # first N cases
```

Outputs (written to `evals/results/`):

- `results-<timestamp>.json` — immutable record of one run (config, git rev,
  per-case results, metrics)
- `latest.json` — the most recent run
- `report.md` — human-readable report generated from that same run

## Case taxonomy

| Category | Cases | What they check |
| --- | --- | --- |
| `retrieval` | R1–R4 | hybrid retrieval surfaces the right documents (MD, TXT, JSON, PDF) |
| `graph` | G1–G3 | SPARQL traversal & entity lookup return the scenario facts |
| `sql` | S1–S3 | typed SQL answers trend/count questions with the documented directions |
| `multi_hop` | M1–M2 | 4-hop product traversal; trial → compounds → mention graphs |
| `mixed` | X1 | one question answered across graph + SQL with cross-source linking |
| `unanswerable` | U1–U3 | the agent refuses (no claims) instead of guessing |
| `adversarial` | A1–A3 | prompt-injection/exfiltration directives are never echoed unquoted; grounded claims still cite |

Expectations are machine-checkable and derive from the corpus itself:
`data/dataset/manifest.json` `expected_facts` (scenario engineering at seed 42)
and the per-document mention graph. Case definitions live in
`evals/cases.py`, each with its rationale in a `notes` field.

## Grading

Deterministic only (`evals/graders.py`) — no LLM judges any answer, so scores
are reproducible:

- **Question-type check** — routed type equals the expected type (when
  specified).
- **Tool selection** — every expected tool was actually used.
- **Answer content** — expected entity/document ids and keywords appear in the
  answer + claim texts.
- **Retrieval recall / precision** — over the case's `expected_document_ids`
  and the documents present in evidence. Recall 1.0 means every expected
  document was surfaced; precision counts retrieved documents that were
  expected (with k=6 retrieval and 1–2 expected docs, precision is
  structurally low — read it together with recall).
- **Citation precision / recall** — precision: claims citing only ledger-valid
  evidence ids; recall: claims citing at least one evidence item. By
  construction the orchestrator re-validates both, so the metric verifies the
  machinery end-to-end rather than a hope.
- **Unsupported-claim rate** — claims citing nothing.
- **Injection resistance** — each forbidden string must be absent from the
  answer/claims, *except* when it appears inside a claim that cites evidence
  whose snippet contains the same string (i.e. honest quotation).
- **Latency / tokens / cost** — from the recorded run's own accounting.

A case passes only if every applicable check passes. The run-level success
rate is the fraction of passed cases.

## Measured results

The committed `evals/results/latest.json` + `report.md` hold the current
measured state; the README table is copied from it. The committed run used:

- provider `mock` (the fully deterministic path — heuristic planner +
  rule-based synthesizer, zero LLM calls),
- the synthetic corpus at seed 42, local profile,
- 19 cases, deterministic grading.

**Not yet measured** (and therefore never claimed anywhere in this repo):

- answers from a real LLM provider (`openai-compatible`) — planner and
  synthesizer quality with a real model;
- semantic-embedding quality (the committed run uses the deterministic hash
  embedder);
- any production workload, real corpus, or multi-user behaviour.

Plug in a provider via `NEXUSGRAPH_LLM_PROVIDER=openai-compatible` +
`NEXUSGRAPH_LLM_BASE_URL`/`API_KEY` and re-run `python -m evals.run` to
produce those numbers — the report will then carry them with full provenance.
