import csv
import json
from pathlib import Path

import pyoxigraph as ox
import pytest

from nexusgraph.synth import build_corpus, generate_dataset

ONTOLOGY = Path(__file__).parents[2] / "ontology" / "nexusgraph.ttl"


def test_generation_is_reproducible(tmp_path: Path) -> None:
    manifest_a = generate_dataset(tmp_path / "a")
    manifest_b = generate_dataset(tmp_path / "b")
    assert manifest_a == manifest_b
    for rel in ("entities.csv", "relationships.csv", "graph.ttl",
                "tables/site_metrics_monthly.csv", "documents_index.json"):
        assert (tmp_path / "a" / rel).read_bytes() == (tmp_path / "b" / rel).read_bytes(), rel


def test_manifest_counts_and_expected_facts(tmp_path: Path) -> None:
    manifest = generate_dataset(tmp_path)
    assert manifest["synthetic"] is True
    counts = manifest["counts"]
    assert counts["entities"] > 100
    assert counts["documents"] >= 14
    assert counts["tables"]["site_metrics_monthly"] > 400
    facts = manifest["expected_facts"]
    assert facts["declining_enrolment_rising_cost_sites"] == ["S-1001", "S-1007", "S-1013"]
    assert facts["trials_with_delayed_milestones"] == ["T-2001", "T-2005", "T-2009"]
    assert facts["region_rising_enrolment_declining_capacity"] == "R-02"


def test_scenario_site_metrics(tmp_path: Path) -> None:
    generate_dataset(tmp_path)
    with (tmp_path / "tables" / "site_metrics_monthly.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    s1001 = [r for r in rows if r["site_id"] == "S-1001" and r["trial_id"] == "T-2001"]
    s1002 = [r for r in rows if r["site_id"] == "S-1002" and r["trial_id"] == "T-2001"]
    assert len(s1001) == 12 and len(s1002) == 12
    # Site A declining enrolment, rising cost; Site B the opposite
    assert int(s1001[0]["patients_enrolled"]) > int(s1001[-1]["patients_enrolled"])
    assert int(s1001[-1]["operational_cost"]) > int(s1001[0]["operational_cost"])
    assert int(s1002[-1]["patients_enrolled"]) > int(s1002[0]["patients_enrolled"])


def test_scenario_capacity_trend(tmp_path: Path) -> None:
    generate_dataset(tmp_path)
    with (tmp_path / "tables" / "investigator_capacity_monthly.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows, "capacity table must not be empty"


def test_adversarial_documents_flagged(tmp_path: Path) -> None:
    generate_dataset(tmp_path)
    index = json.loads((tmp_path / "documents_index.json").read_text(encoding="utf-8"))
    adv = [d for d in index if d["adversarial"]]
    assert len(adv) == 2
    assert all(d["mentions"] for d in adv)
    d9013 = next(d for d in adv if d["doc_id"] == "D-9013")
    assert (tmp_path / "documents" / d9013["filename"]).exists()


def test_pdf_document_rendered(tmp_path: Path) -> None:
    generate_dataset(tmp_path)
    pdf_path = tmp_path / "documents" / "site_audit_S-1001_2025.pdf"
    assert pdf_path.exists() and pdf_path.read_bytes().startswith(b"%PDF")
    from pypdf import PdfReader

    text = "".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)
    assert "S-1001" in text and "T-2001" in text


def test_data_graph_parses_and_answers_sparql(tmp_path: Path) -> None:
    generate_dataset(tmp_path)
    store = ox.Store()
    store.load(path=tmp_path / "graph.ttl", format=ox.RdfFormat.TURTLE)
    assert len(store) > 500
    # trial -> compounds via ontology property
    result = store.query(
        "PREFIX ngx: <https://nexusgraph.dev/ontology#>\n"
        "SELECT ?c WHERE { ?t ngx:name 'AURORA-2' . ?t ngx:TRIAL_USES_COMPOUND ?c }"
    )
    compounds = sorted(str(row["c"].value).rsplit("/", 1)[-1] for row in result)
    assert compounds == ["C-5001", "C-5002"]


def test_ontology_file_parses() -> None:
    store = ox.Store()
    store.load(path=ONTOLOGY, format=ox.RdfFormat.TURTLE)
    result = store.query(
        "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
        "SELECT (COUNT(?c) AS ?n) WHERE { ?c a owl:Class }"
    )
    classes = int(next(iter(result))["n"].value)
    assert classes >= 13


def test_aliases_include_site_a_and_b(tmp_path: Path) -> None:
    corpus = build_corpus()
    assert corpus.aliases["Site A"] == "site:S-1001"
    assert corpus.aliases["Site B"] == "site:S-1002"
    assert corpus.aliases["AURORA-2"] == "trial:T-2001"


@pytest.mark.parametrize(
    "doc_id,needle",
    [
        ("D-9001", "S-1001"),
        ("D-9005", "SE-11001"),
        ("D-9008", "Western Europe Cluster"),
        ("D-9013", "NXG-SECRET-2024"),
    ],
)
def test_document_contents(tmp_path: Path, doc_id: str, needle: str) -> None:
    generate_dataset(tmp_path)
    index = json.loads((tmp_path / "documents_index.json").read_text(encoding="utf-8"))
    entry = next(d for d in index if d["doc_id"] == doc_id)
    text = (tmp_path / "documents" / entry["filename"]).read_text(encoding="utf-8")
    assert needle in text
