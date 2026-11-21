# Retrieval ablation

Run with `uv run python -m benchmarks.run_ablation --results benchmarks/RESULTS.md`.

The offline suite uses the seed-42 synthetic corpus plus the operational
records in `evals/diagnostic.py`. Every mode uses the same corpus, 256-dimensional
hash embeddings, candidate depth, context budget, planner and synthesizer.

Ranking uses unique document IDs from the raw ranking and only queries with
authored relevance labels. The answer stage runs all cases. Citation precision
counts emitted document claim-to-source links with a verbatim span at the stored
location, a relevant document ID and, where annotated, an answer anchor in the
span. The packed baseline counts relevant, source-verified passages in the
same candidates before synthesis, using the Wave 5 packer coverage rule. It
measures candidate quality on this corpus. The answer and packed columns count
different units, so both denominators are shown.

Refusal accuracy uses the unanswerable category. The packed baseline uses the
absence of packed retrieval hits. Answer coverage measures how often the agent
answers labeled answerable document questions. Answer pass rate also requires
the expected anchors and sources. Hygiene pass rate requires the directive
to reach the context packer and its canary to stay out of the answer and
returned evidence. These measurements characterize the offline configuration.
The thresholds were developed with this diagnostic suite, so the results
are development measurements on a synthetic corpus.

## Overall ranking (60 total diagnostic queries)

| Configuration | Queries | MRR@10 | Recall@5 | NDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| Dense-only | 33 | 0.8687 | 1.0000 | 0.8919 |
| Hybrid RRF | 33 | 0.9242 | 1.0000 | 0.9368 |
| Hybrid RRF + Reranker | 33 | 0.9848 | 1.0000 | 0.9888 |

## Ranking by category

| Configuration | Category | Queries | MRR@10 | Recall@5 | NDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: |
| Dense-only | retrieval | 4 | 1.0000 | 1.0000 | 1.0000 |
| Dense-only | exact | 9 | 0.8333 | 1.0000 | 0.8770 |
| Dense-only | near_miss | 8 | 0.7917 | 1.0000 | 0.8452 |
| Dense-only | multi_hop | 8 | 0.8542 | 1.0000 | 0.8472 |
| Dense-only | document_hygiene | 4 | 1.0000 | 1.0000 | 1.0000 |
| Hybrid RRF | retrieval | 4 | 1.0000 | 1.0000 | 1.0000 |
| Hybrid RRF | exact | 9 | 1.0000 | 1.0000 | 1.0000 |
| Hybrid RRF | near_miss | 8 | 0.8125 | 1.0000 | 0.8616 |
| Hybrid RRF | multi_hop | 8 | 0.8750 | 1.0000 | 0.8779 |
| Hybrid RRF | document_hygiene | 4 | 1.0000 | 1.0000 | 1.0000 |
| Hybrid RRF + Reranker | retrieval | 4 | 1.0000 | 1.0000 | 1.0000 |
| Hybrid RRF + Reranker | exact | 9 | 1.0000 | 1.0000 | 1.0000 |
| Hybrid RRF + Reranker | near_miss | 8 | 0.9375 | 1.0000 | 0.9539 |
| Hybrid RRF + Reranker | multi_hop | 8 | 1.0000 | 1.0000 | 1.0000 |
| Hybrid RRF + Reranker | document_hygiene | 4 | 1.0000 | 1.0000 | 1.0000 |

## Answer quality and packed baseline

| Configuration | Packed precision | Citation precision | Packed refusal | Refusal accuracy | Answer coverage | Answer pass rate | Hygiene pass rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dense-only | 0.6364 (42/66) | 1.0000 (41/41) | 0.6923 (9/13) | 1.0000 (13/13) | 1.0000 (33/33) | 1.0000 (33/33) | 1.0000 (6/6) |
| Hybrid RRF | 0.6364 (42/66) | 1.0000 (41/41) | 0.6923 (9/13) | 1.0000 (13/13) | 1.0000 (33/33) | 1.0000 (33/33) | 1.0000 (6/6) |
| Hybrid RRF + Reranker | 0.6364 (42/66) | 1.0000 (41/41) | 0.6923 (9/13) | 1.0000 (13/13) | 1.0000 (33/33) | 1.0000 (33/33) | 1.0000 (6/6) |
