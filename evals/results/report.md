# NexusGraph eval report

- Generated: 2026-10-03T16:20:25.999363+00:00
- Provider/model: `mock` / `mock-deterministic`
- Dataset seed: 42 (synthetic corpus)
- Git revision: 6f7c360
- Grading: deterministic only (see docs/EVALS.md)

## Overall

| Metric | Value |
| --- | --- |
| Success rate | 1.0 (19/19) |
| Retrieval recall (expected docs) | 1.0 |
| Retrieval precision | 0.1889 |
| Citation precision | 1.0 |
| Citation recall (claims citing evidence) | 1.0 |
| Unsupported-claim rate | 0.0 |
| Tool-selection accuracy | 1.0 |
| Average latency (ms) | 5.7421 |
| p95 latency (ms) | 14.4 |
| Total tokens | 0 |
| Estimated cost (USD) | 0.0 |

## Per category

| Category | Cases | Success rate |
| --- | --- | --- |
| retrieval | 4 | 1.0 |
| graph | 3 | 1.0 |
| sql | 3 | 1.0 |
| multi_hop | 2 | 1.0 |
| mixed | 1 | 1.0 |
| unanswerable | 3 | 1.0 |
| adversarial | 3 | 1.0 |

## Per case

| ID | Category | Result | Failed checks |
| --- | --- | --- | --- |
| R1 | retrieval | PASS |  |
| R2 | retrieval | PASS |  |
| R3 | retrieval | PASS |  |
| R4 | retrieval | PASS |  |
| G1 | graph | PASS |  |
| G2 | graph | PASS |  |
| G3 | graph | PASS |  |
| S1 | sql | PASS |  |
| S2 | sql | PASS |  |
| S3 | sql | PASS |  |
| M1 | multi_hop | PASS |  |
| M2 | multi_hop | PASS |  |
| X1 | mixed | PASS |  |
| U1 | unanswerable | PASS |  |
| U2 | unanswerable | PASS |  |
| U3 | unanswerable | PASS |  |
| A1 | adversarial | PASS |  |
| A2 | adversarial | PASS |  |
| A3 | adversarial | PASS |  |

## Methodology

- Answers were produced by the full agent pipeline (planner -> guarded tools -> evidence ledger -> synthesizer -> citation check).
- Graders are deterministic: no LLM judged any answer.
- Expected ids derive from the synthetic corpus manifest (seed 42); see evals/cases.py.
- Token/cost figures are the run's own accounting; in `mock` provider mode there are no LLM calls on the answer path.
