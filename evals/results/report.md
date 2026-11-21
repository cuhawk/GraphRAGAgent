# NexusGraph eval report

- Generated: 2026-11-21T03:11:34.571554+00:00
- Provider/model: `mock` / `mock-deterministic`
- Dataset seed: 42 (synthetic corpus + diagnostic records)
- Git revision: 218bf96
- Grading: deterministic only (see docs/EVALS.md)

## Overall

| Metric | Value |
| --- | --- |
| Success rate | 1.0 (60/60) |
| Retrieval recall (expected docs) | 1.0 |
| Retrieval precision | 1.0 |
| Citation precision | 1.0 |
| Citation recall (claims citing evidence) | 1.0 |
| Unsupported-claim rate | 0.0 |
| Tool-selection accuracy | 1.0 |
| Average latency (ms) | 10.5783 |
| p95 latency (ms) | 16.2 |
| Total tokens | 0 |
| Estimated cost (USD) | 0.0 |

## Per category

| Category | Cases | Success rate |
| --- | --- | --- |
| retrieval | 4 | 1.0 |
| graph | 3 | 1.0 |
| sql | 3 | 1.0 |
| multi_hop | 10 | 1.0 |
| mixed | 1 | 1.0 |
| unanswerable | 13 | 1.0 |
| adversarial | 3 | 1.0 |
| exact | 9 | 1.0 |
| near_miss | 8 | 1.0 |
| document_hygiene | 6 | 1.0 |

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
| E1 | exact | PASS |  |
| E2 | exact | PASS |  |
| E3 | exact | PASS |  |
| E4 | exact | PASS |  |
| E5 | exact | PASS |  |
| E6 | exact | PASS |  |
| E7 | exact | PASS |  |
| E8 | exact | PASS |  |
| E9 | exact | PASS |  |
| N1 | near_miss | PASS |  |
| N2 | near_miss | PASS |  |
| N3 | near_miss | PASS |  |
| N4 | near_miss | PASS |  |
| N5 | near_miss | PASS |  |
| N6 | near_miss | PASS |  |
| N7 | near_miss | PASS |  |
| N8 | near_miss | PASS |  |
| J1 | multi_hop | PASS |  |
| J2 | multi_hop | PASS |  |
| J3 | multi_hop | PASS |  |
| J4 | multi_hop | PASS |  |
| J5 | multi_hop | PASS |  |
| J6 | multi_hop | PASS |  |
| J7 | multi_hop | PASS |  |
| J8 | multi_hop | PASS |  |
| U4 | unanswerable | PASS |  |
| U5 | unanswerable | PASS |  |
| U6 | unanswerable | PASS |  |
| U7 | unanswerable | PASS |  |
| U8 | unanswerable | PASS |  |
| U9 | unanswerable | PASS |  |
| U10 | unanswerable | PASS |  |
| U11 | unanswerable | PASS |  |
| U12 | unanswerable | PASS |  |
| U13 | unanswerable | PASS |  |
| H1 | document_hygiene | PASS |  |
| H2 | document_hygiene | PASS |  |
| H3 | document_hygiene | PASS |  |
| H4 | document_hygiene | PASS |  |
| H5 | document_hygiene | PASS |  |
| H6 | document_hygiene | PASS |  |

## Methodology

- Answers were produced by the full agent pipeline (planner -> guarded tools -> evidence ledger -> synthesizer -> citation check).
- Graders are deterministic: no LLM judged any answer.
- Expected sources and answer anchors are specified in evals/cases.py and evals/diagnostic.py.
- Token/cost figures are the run's own accounting; in `mock` provider mode there are no LLM calls on the answer path.
