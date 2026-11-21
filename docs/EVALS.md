# Evaluations

The agent report and the retrieval ablation publish results from executed runs.
The ablation report is in `benchmarks/RESULTS.md`.

## Running

```bash
uv run python -m evals.run                 # full diagnostic suite
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
| `multi_hop` | M1–M2, J1–J8 | Graph traversal and evidence joined across operational records |
| `mixed` | X1 | one question answered across graph + SQL with cross-source linking |
| `unanswerable` | U1–U13 | Refusal for absent entities, missing fields, and out-of-domain questions |
| `adversarial` | A1–A3 | Direct user instructions to repeat fixture payloads |
| `exact` | E1–E9 | Identifier, code, and table-cell lookups |
| `near_miss` | N1–N8 | Relevant passages among similar operational records |
| `document_hygiene` | H1–H6 | Retrieved directives and clean factual spans |

The runner builds a fresh offline database with the seed-42 corpus and
the operational packet in `evals/diagnostic.py`. The cases specify expected
tools, sources, answer anchors, and refusal behavior.

## Grading

Deterministic only (`evals/graders.py`) — no LLM judges any answer, so scores
are reproducible:

- **Question-type check** — routed type equals the expected type (when
  specified).
- **Tool selection** — every expected tool was actually used.
- **Answer content** — expected entity/document ids and keywords appear in the
  answer + claim texts.
- **Evidence recall / precision** measure expected documents represented in
  the final answer's evidence. The ablation separately measures raw ranking.
- **Citation precision / recall** measure valid claim-to-source links and
  supported claims. Document citations require a verbatim span and any authored
  source-specific answer anchors. The ablation also checks the stored chunk.
- **Unsupported-claim rate** counts claims without valid support.
- **Injection resistance** checks canary absence in the answer, claims, and
  evidence. Document-hygiene cases also verify that the directive was retrieved
  into the candidate context.
- **Latency / tokens / cost** — from the recorded run's own accounting.

A case passes only if every applicable check passes. The run-level success
rate is the fraction of passed cases.

## Measured results

The latest run is recorded in `evals/results/latest.json` and
`evals/results/report.md`. Both the diagnostic suite and the ablation run
the local mock planner and synthesizer with hash embeddings. The measurements
describe this synthetic development corpus. Live model providers, semantic
embeddings, and production workloads require separate evaluation.
