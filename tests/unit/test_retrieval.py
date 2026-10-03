from nexusgraph.retrieval.bm25 import bm25_scores
from nexusgraph.retrieval.embeddings import HashEmbedder, make_embedder
from nexusgraph.store.vector import LocalVectorIndex


def test_hash_embedder_deterministic_and_normalized() -> None:
    embedder = HashEmbedder(dim=256)
    a1 = embedder.embed_texts(["Site A enrolment declined"])[0]
    a2 = embedder.embed_texts(["Site A enrolment declined"])[0]
    b = embedder.embed_texts(["compound storage excursion"])[0]
    assert a1 == a2
    assert len(a1) == 256
    assert abs(sum(x * x for x in a1) - 1.0) < 1e-6
    sim = sum(x * y for x, y in zip(a1, b, strict=True))
    assert sim < 0.9  # different texts are not identical


def test_make_embedder_default_hash() -> None:
    from nexusgraph.config import LLMSettings

    embedder = make_embedder(LLMSettings())
    assert isinstance(embedder, HashEmbedder)


def test_bm25_scores_rank_relevant_first() -> None:
    docs = [
        "Site A enrolment declined while costs increased",
        "compound storage temperature excursion",
        "investigator capacity index in Western Europe",
    ]
    scores = bm25_scores("enrolment declined site", docs)
    assert scores[0] == max(scores)
    assert scores[0] > 0.0


def test_local_vector_index_roundtrip(engine, document_store) -> None:
    from nexusgraph.domain.models import Chunk, DocumentMeta
    from nexusgraph.retrieval.embeddings import HashEmbedder

    document_store.upsert_document(DocumentMeta(
        id="doc:D-9001", title="Ops review", content_type="text/markdown",
        source_path="x.md", text="Site A enrolment declined while costs increased.",
    ))
    embedder = HashEmbedder()
    document_store.replace_chunks("doc:D-9001", [
        Chunk(id="doc:D-9001#chunk-0001", document_id="doc:D-9001", ordinal=1,
              text="Site A enrolment declined while costs increased.",
              embedding=embedder.embed_texts(
                  ["Site A enrolment declined while costs increased."])[0]),
    ])
    index = LocalVectorIndex(engine)
    assert index.refresh() == 1
    query = embedder.embed_texts(["enrolment decline at Site A"])[0]
    hits = index.search(query, k=3)
    assert hits and hits[0].chunk_id == "doc:D-9001#chunk-0001"
    assert 0.5 < hits[0].dense_score <= 1.0
