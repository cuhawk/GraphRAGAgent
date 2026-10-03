"""RDF emission for the synthetic corpus.

Builds the entity/relationship data graph (default graph) with pyoxigraph and
serialises it to Turtle. Document-mention triples are deliberately *not*
emitted here: they are derived at ingestion time (deterministic extraction)
and stored in per-document named graphs for provenance scoping.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pyoxigraph as ox

from nexusgraph.domain.ids import ONTOLOGY_BASE, entity_uri
from nexusgraph.synth.generator import Corpus

XSD = "http://www.w3.org/2001/XMLSchema#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

TYPE_TO_CLASS: dict[str, str] = {
    "company": "Company",
    "product": "Product",
    "compound": "Compound",
    "trial": "ClinicalTrial",
    "site": "TrialSite",
    "hospital": "Hospital",
    "investigator": "Investigator",
    "country": "Country",
    "region": "Region",
    "safetyevent": "SafetyEvent",
    "milestone": "Milestone",
}

_PHASE_INDIVIDUAL = {"Phase I": "phase_1", "Phase II": "phase_2", "Phase III": "phase_3"}


def _nn(iri: str) -> ox.NamedNode:
    return ox.NamedNode(iri)


def _lit(value: str, datatype: str = f"{XSD}string") -> ox.Literal:
    return ox.Literal(value, datatype=_nn(datatype))


def build_data_graph(corpus: Corpus) -> ox.Store:
    """Return an in-memory store with entity + relationship + attribute triples."""
    store = ox.Store()
    ngx = ONTOLOGY_BASE

    entities_by_type: dict[str, dict[str, Any]] = {}
    for e in corpus.entities:
        entities_by_type.setdefault(e.type, {})[e.id] = e

    # Trial attribute tables (source of typed literals in RDF)
    trial_rows = {str(r["trial_id"]): r for r in corpus.tables.get("trials", [])}
    milestone_rows = {str(r["milestone_id"]): r
                      for r in corpus.tables.get("milestones", [])}
    safety_rows = {str(r["event_id"]): r for r in corpus.tables.get("safety_events", [])}

    for e in corpus.entities:
        subject = _nn(entity_uri(e.type, e.id.split(":", 1)[1]))
        cls = TYPE_TO_CLASS.get(e.type)
        if cls:
            store.add(ox.Quad(subject, _nn(RDF_TYPE), _nn(ngx + cls), ox.DefaultGraph()))
        store.add(ox.Quad(subject, _nn(ngx + "name"), _lit(e.name), ox.DefaultGraph()))
        if e.description:
            store.add(ox.Quad(subject, _nn(ngx + "description"), _lit(e.description),
                              ox.DefaultGraph()))

        if e.type == "trial":
            row = trial_rows[e.id.split(":", 1)[1]]
            store.add(ox.Quad(subject, _nn(ngx + "inPhase"),
                              _nn(ngx + _PHASE_INDIVIDUAL[str(row["phase"])]),
                              ox.DefaultGraph()))
            store.add(ox.Quad(subject, _nn(ngx + "status"),
                              _lit(str(row["status"])), ox.DefaultGraph()))
            store.add(ox.Quad(subject, _nn(ngx + "startDate"),
                              _lit(str(row["start_date"]), f"{XSD}date"), ox.DefaultGraph()))
            store.add(ox.Quad(subject, _nn(ngx + "plannedEndDate"),
                              _lit(str(row["planned_end_date"]), f"{XSD}date"),
                              ox.DefaultGraph()))
        elif e.type == "milestone":
            row = milestone_rows[e.id.split(":", 1)[1]]
            store.add(ox.Quad(subject, _nn(ngx + "dueDate"),
                              _lit(str(row["due_date"]), f"{XSD}date"), ox.DefaultGraph()))
            if row["completed_date"]:
                store.add(ox.Quad(subject, _nn(ngx + "completedDate"),
                                  _lit(str(row["completed_date"]), f"{XSD}date"),
                                  ox.DefaultGraph()))
        elif e.type == "safetyevent":
            row = safety_rows[e.id.split(":", 1)[1]]
            store.add(ox.Quad(subject, _nn(ngx + "severity"),
                              _lit(str(row["severity"])), ox.DefaultGraph()))
            store.add(ox.Quad(subject, _nn(ngx + "reportedAt"),
                              _lit(str(row["reported_at"]), f"{XSD}date"), ox.DefaultGraph()))

    for src, dst, rel in corpus.relationships:
        src_type, src_local = src.split(":", 1)
        dst_type, dst_local = dst.split(":", 1)
        store.add(ox.Quad(
            _nn(entity_uri(src_type, src_local)),
            _nn(ngx + rel),
            _nn(entity_uri(dst_type, dst_local)),
            ox.DefaultGraph(),
        ))
    return store


def write_turtle(store: ox.Store, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    store.dump(path, ox.RdfFormat.TURTLE, from_graph=ox.DefaultGraph())
