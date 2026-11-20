from nexusgraph.config import LimitsSettings
from nexusgraph.domain.models import Chunk, DocumentMeta
from nexusgraph.ingestion.chunking import chunk_document
from nexusgraph.retrieval.context import context_token_count
from nexusgraph.retrieval.embeddings import HashEmbedder
from nexusgraph.retrieval.service import RetrievalService, reciprocal_rank_fusion
from nexusgraph.store.vector import LocalVectorIndex


def test_markdown_table_continuations_repeat_headers_with_source_lines() -> None:
    text = (
        "Product manual\n==============\n\n## Advisories\n\n"
        "| SKU | Advisory | Count |\n| --- | --- | ---: |\n"
        "| NXG-11.A | CVE-2099-0001 | 123.45 |\n"
        "| NXG-12.B | CVE-2099-0002 | 678.90 |\n"
    )
    first, second = chunk_document(text, "text/markdown", max_chars=95)
    assert first.headings == second.headings == ("Product manual", "Advisories")
    assert first.start_line == 8
    assert second.start_line == second.end_line == 9
    assert second.contextual_text.startswith("Product manual > Advisories\n\n| SKU")
    assert "| NXG-12.B | CVE-2099-0002 | 678.90 |" in second.text


def test_html_table_keeps_headers_and_csv_keeps_multiline_cells() -> None:
    html = """<h1>Inventory</h1>
<h2>Stock</h2>
<table><thead><tr><th>SKU</th><th>Units</th></tr></thead>
<tr><td>A-1000</td><td>123</td></tr>
<tr><td>A-1001</td><td>456</td></tr></table>
<script>ignored content</script>"""
    first, second = chunk_document(html, "text/html", max_chars=100)
    assert first.headings == second.headings == ("Inventory", "Stock")
    assert second.start_line == 5
    assert "<th>SKU</th><th>Units</th>" in second.text
    assert "<td>A-1001</td><td>456</td>" in second.text
    assert "ignored" not in second.text
    csv = 'SKU,Notes,Units\nA-001,"first\nsecond",123\nA-002,third,456\n'
    first, second = chunk_document(csv, "text/csv", max_chars=40)
    assert (first.start_line, first.end_line) == (2, 3)
    assert first.text.endswith('A-001,"first\nsecond",123')
    assert second.text == "SKU,Notes,Units\nA-002,third,456"


def test_sparse_only_chunk_survives_fusion_and_packs_whole(engine, document_store) -> None:
    document_store.upsert_document(
        DocumentMeta(id="manual", title="Manual", content_type="text/markdown", source_path="m.md")
    )
    text = "| SKU | Count |\n| --- | --- |\n| AX-0001 | 123.45 |"
    document_store.replace_chunks(
        "manual",
        [
            Chunk(
                id="sparse",
                document_id="manual",
                ordinal=1,
                text=text,
                metadata={
                    "headings": ["Inventory"],
                    "start_line": 7,
                    "provenance": {"location": "[manual:Inventory:7]"},
                },
            )
        ],
    )
    service = RetrievalService(
        document_store, LocalVectorIndex(engine), HashEmbedder(), LimitsSettings()
    )
    query = "Count AX-0001"
    assert service.rank(query, depth=10, mode="dense") == []
    ranked = service.rank(query, depth=10)
    assert ranked[0].score == 1 / 61
    packed = service.pack(ranked, k=1)
    assert packed.text == f"[manual:Inventory:7]\nInventory\n\n{text}"
    assert packed.token_count == context_token_count(packed.text)
    assert not service.search("Count AX-0002")
    assert reciprocal_rank_fusion(["a", "b"], ["b"]) == {"a": 1 / 61, "b": 1 / 62 + 1 / 61}
