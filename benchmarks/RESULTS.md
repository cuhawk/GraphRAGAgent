# Retrieval ablation

Run with `uv run python -m benchmarks.run_ablation` to print the measured table.

All eval questions ran against a fresh seed-42 corpus with offline hash embeddings. Ranking metrics use unique document IDs and cases with document relevance labels. Citation precision is the fraction of packed citations with a matching stored source and a gold document ID on those same cases. Refusal accuracy is measured on the unanswerable cases. All configurations share the evidence gate and context budgets.

| Configuration | MRR@10 | Recall@5 | NDCG@10 | Citation precision | Refusal accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dense-only | 1.0000 | 1.0000 | 1.0000 | 0.4375 | 0.3333 |
| Hybrid RRF | 1.0000 | 1.0000 | 1.0000 | 0.4375 | 0.3333 |
| Hybrid RRF + Reranker | 1.0000 | 1.0000 | 1.0000 | 0.4375 | 0.3333 |
