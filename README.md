# NexusGraph

> Work in progress — full README lands with the documentation phase (see `PLAN.md`).

NexusGraph is a GraphRAG + Knowledge Graph Agent that answers complex enterprise questions
by routing across RDF/SPARQL, SQL, and vector retrieval — with citations, provenance and
traces. All bundled domain data is synthetic.

Quick start (local, no services):

```bash
uv sync --extra dev
uv run nexusgraph bootstrap
uv run nexusgraph serve
```

Until the full README is written, see `PLAN.md` and `docs/`.
