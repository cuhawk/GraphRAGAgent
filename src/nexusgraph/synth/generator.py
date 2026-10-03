"""Synthetic life-sciences dataset generation.

Everything in the generated corpus is fictional and reproducible: a fixed seed
drives a dedicated ``random.Random`` instance (never the global RNG), and all
iteration order is explicit.

The corpus deliberately embeds findable "business patterns" so that example
questions and evaluation cases have deterministic gold answers:

- ``Site A`` (``site:S-1001``): declining enrolment + rising operational cost,
  five operational safety events, and a delayed trial milestone (via T-2001).
- ``Site B`` (``site:S-1002``): rising enrolment, stable costs, zero safety events.
- Trials with delayed milestones: T-2001, T-2005, T-2009 -> their compounds'
  derived products are the gold answer to "products linked to delayed studies".
- ``Western Europe Cluster``: rising enrolment but declining investigator
  capacity (distractor regions trend differently).
- Two clearly-labelled adversarial documents for prompt-injection evaluation.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from random import Random

MONTHS: list[str] = [
    "2024-07", "2024-08", "2024-09", "2024-10", "2024-11", "2024-12",
    "2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06",
]

REGIONS: list[tuple[str, str]] = [
    ("R-01", "Nordic Cluster"),
    ("R-02", "Western Europe Cluster"),
    ("R-03", "Central European Cluster"),
    ("R-04", "Iberian Cluster"),
    ("R-05", "North Atlantic Cluster"),
    ("R-06", "Baltic Cluster"),
]

COUNTRIES: list[tuple[str, str, str]] = [  # id, name, region_id
    ("CT-101", "Aldenmark", "R-01"),
    ("CT-102", "Sjoland", "R-01"),
    ("CT-103", "Corvania", "R-02"),
    ("CT-104", "Luxford", "R-02"),
    ("CT-105", "Deltara", "R-03"),
    ("CT-106", "Grunwald", "R-03"),
    ("CT-107", "Marovia", "R-03"),
    ("CT-108", "Solterra", "R-04"),
    ("CT-109", "Valdorra", "R-04"),
    ("CT-110", "Borealia", "R-05"),
    ("CT-111", "New Halvard", "R-05"),
    ("CT-112", "Estmark", "R-06"),
    ("CT-113", "Vindeln", "R-06"),
]

HOSPITALS: list[tuple[str, str, str]] = [  # id, name, country_id
    ("H-6001", "Nordhaven University Hospital", "CT-101"),
    ("H-6002", "Marrow Creek Medical Center", "CT-103"),
    ("H-6003", "Deltara Regional Clinic", "CT-105"),
    ("H-6004", "Solterra Health Institute", "CT-108"),
    ("H-6005", "Borealia General Hospital", "CT-110"),
    ("H-6006", "Luxford Clinical Sciences Centre", "CT-104"),
    ("H-6007", "Grunwald University Medical Campus", "CT-106"),
    ("H-6008", "Estmark Coastal Hospital", "CT-112"),
]

COMPANIES: list[tuple[str, str, str]] = [  # id, name, hq_country
    ("CO-8001", "Meridian Biosciences", "CT-103"),
    ("CO-8002", "Helixor Therapeutics", "CT-101"),
    ("CO-8003", "Calderon Pharma", "CT-108"),
]

COMPOUNDS: list[tuple[str, str, str]] = [  # id, name (NXG-code), fictional target
    ("C-5001", "NXG-101", "NX-K1 kinase"),
    ("C-5002", "NXG-102", "NX-K2 transporter"),
    ("C-5003", "NXG-103", "NX-P3 phosphatase"),
    ("C-5004", "NXG-104", "NX-R4 receptor"),
    ("C-5005", "NXG-105", "NX-M5 metabolic pathway"),
    ("C-5006", "NXG-106", "NX-R6 receptor"),
    ("C-5007", "NXG-107", "NX-K7 kinase"),
    ("C-5008", "NXG-108", "NX-P8 phosphatase"),
    ("C-5009", "NXG-109", "NX-T9 ion channel"),
    ("C-5010", "NXG-110", "NX-K10 kinase"),
    ("C-5011", "NXG-111", "NX-M11 metabolic pathway"),
    ("C-5012", "NXG-112", "NX-R12 receptor"),
]

PRODUCTS: list[tuple[str, str, str, str]] = [  # id, name, company_id, compound_id
    ("P-4001", "Aurolet", "CO-8001", "C-5001"),
    ("P-4002", "Breximab", "CO-8001", "C-5002"),
    ("P-4003", "Caldevar", "CO-8003", "C-5003"),
    ("P-4004", "Doranex", "CO-8003", "C-5004"),
    ("P-4005", "Elvotin", "CO-8002", "C-5005"),
    ("P-4006", "Ferzana", "CO-8001", "C-5006"),
    ("P-4007", "Gliovex", "CO-8002", "C-5009"),
    ("P-4008", "Hydremol", "CO-8003", "C-5010"),
]

TRIALS: list[tuple[str, str, str, str, str]] = [  # id, codename, phase, company_id, status
    ("T-2001", "AURORA-2", "Phase II", "CO-8001", "ongoing"),
    ("T-2002", "BOREALIS-1", "Phase III", "CO-8002", "ongoing"),
    ("T-2003", "CASCADE-3", "Phase II", "CO-8001", "ongoing"),
    ("T-2004", "DELTAWAVE", "Phase I", "CO-8003", "completed"),
    ("T-2005", "EMBER-2", "Phase II", "CO-8002", "ongoing"),
    ("T-2006", "FATHOM-1", "Phase III", "CO-8001", "ongoing"),
    ("T-2007", "GLACIER-4", "Phase II", "CO-8003", "completed"),
    ("T-2008", "HORIZON-2", "Phase I", "CO-8001", "ongoing"),
    ("T-2009", "IRIS-3", "Phase II", "CO-8002", "ongoing"),
    ("T-2010", "JUNCTURE-1", "Phase III", "CO-8003", "ongoing"),
]

TRIAL_COMPOUNDS: dict[str, list[str]] = {
    "T-2001": ["C-5001", "C-5002"],
    "T-2002": ["C-5003"],
    "T-2003": ["C-5004", "C-5006"],
    "T-2004": ["C-5007"],
    "T-2005": ["C-5005"],
    "T-2006": ["C-5006", "C-5008"],
    "T-2007": ["C-5010"],
    "T-2008": ["C-5002"],
    "T-2009": ["C-5009"],
    "T-2010": ["C-5011", "C-5012"],
}

TRIAL_SITES: dict[str, list[str]] = {
    "T-2001": ["S-1001", "S-1002", "S-1003", "S-1004", "S-1005"],
    "T-2002": ["S-1006", "S-1007", "S-1008", "S-1009"],
    "T-2003": ["S-1010", "S-1011", "S-1012", "S-1013"],
    "T-2004": ["S-1014", "S-1015"],
    "T-2005": ["S-1016", "S-1017", "S-1018"],
    "T-2006": ["S-1019", "S-1020", "S-1021"],
    "T-2007": ["S-1022", "S-1023", "S-1024"],
    "T-2008": ["S-1002", "S-1009", "S-1015"],
    "T-2009": ["S-1001", "S-1005", "S-1011", "S-1019"],
    "T-2010": ["S-1003", "S-1007", "S-1013", "S-1017", "S-1021"],
}

# id, name, country_id, hospital_id, metric pattern
SITES: list[tuple[str, str, str, str | None, str]] = [
    ("S-1001", "Site A (Nordhaven University Hospital)", "CT-101", "H-6001",
     "declining_cost_rising"),
    ("S-1002", "Site B (Marrow Creek Medical Center)", "CT-103", "H-6002", "rising"),
    ("S-1003", "Sjoland Coastal Trial Unit", "CT-102", None, "strong_rising"),
    ("S-1004", "Luxford Phase Unit 4", "CT-104", "H-6006", "rising"),
    ("S-1005", "Corvania Central Site", "CT-103", None, "rising"),
    ("S-1006", "Deltara Metropolitan Site", "CT-105", "H-6003", "stable"),
    ("S-1007", "Grunwald Research Site", "CT-106", "H-6007", "declining_cost_rising"),
    ("S-1008", "Corvania West Clinic", "CT-103", None, "rising"),
    ("S-1009", "Marovia Field Site", "CT-107", None, "mild_decline"),
    ("S-1010", "Luxford North Unit", "CT-104", None, "rising"),
    ("S-1011", "Solterra Beach Clinic", "CT-108", "H-6004", "decline"),
    ("S-1012", "Solterra Inland Unit", "CT-108", None, "decline"),
    ("S-1013", "Valdorra Central Site", "CT-109", None, "declining_cost_rising"),
    ("S-1014", "Valdorra Coastal Unit", "CT-109", None, "decline"),
    ("S-1015", "Borealia Metro Site", "CT-110", "H-6005", "rising"),
    ("S-1016", "New Halvard Site 2", "CT-111", None, "rising"),
    ("S-1017", "Borealia North Unit", "CT-110", None, "mild_rise"),
    ("S-1018", "Estmark Trial Hub", "CT-112", "H-6008", "stable"),
    ("S-1019", "Vindeln Lakeside Site", "CT-112", None, "mild_decline"),
    ("S-1020", "Aldenmark Plains Site", "CT-101", None, "mild_rise"),
    ("S-1021", "Deltara South Clinic", "CT-105", None, "stable"),
    ("S-1022", "Grunwald East Unit", "CT-106", None, "mild_rise"),
    ("S-1023", "Marovia Hill Site", "CT-107", None, "stable"),
    ("S-1024", "Sjoland Fjord Unit", "CT-102", None, "mild_rise"),
]

# pattern -> (enrolment_start, enrolment_slope_per_month, cost_start, cost_slope_per_month)
METRIC_PATTERNS: dict[str, tuple[int, float, int, float]] = {
    "declining_cost_rising": (42, -2.4, 118_000, 6_500),
    "rising": (18, 2.2, 95_000, 1_500),
    "strong_rising": (22, 3.0, 88_000, 2_000),
    "stable": (25, 0.05, 102_000, 300),
    "mild_decline": (30, -0.8, 98_000, 900),
    "decline": (28, -1.2, 94_000, 700),
    "mild_rise": (20, 0.9, 91_000, 800),
}

TRIAL_DATES: dict[str, tuple[str, str]] = {  # id -> (start_date, planned_end_date)
    "T-2001": ("2024-04-01", "2026-03-31"),
    "T-2002": ("2023-09-01", "2026-08-31"),
    "T-2003": ("2024-02-01", "2026-01-31"),
    "T-2004": ("2023-05-01", "2025-04-30"),
    "T-2005": ("2024-01-01", "2025-12-31"),
    "T-2006": ("2023-11-01", "2026-10-31"),
    "T-2007": ("2023-07-01", "2025-06-30"),
    "T-2008": ("2024-06-01", "2026-05-31"),
    "T-2009": ("2024-03-01", "2026-02-28"),
    "T-2010": ("2023-08-01", "2026-07-31"),
}

INVESTIGATOR_NAMES: list[str] = [
    "Aino Vikstrom", "Mateo Carreras", "Freja Lindqvist", "Tomas Brandt",
    "Elena Solberg", "Pieter Vandenberg", "Clara Osswald", "Jonas Kettner",
    "Sofia Marchetti", "Lukas Brenner", "Marta Nowicki", "Andre Cazals",
    "Ingrid Halvorsen", "Diego Ferran", "Katja Reinhardt", "Nils Ekstrom",
    "Paula Ribeiro", "Marcus Delvin", "Hana Sorokin", "Oskar Valldal",
    "Renata Almeida", "Viktor Sandell", "Camille Duret", "Sander Holm",
    "Anneli Kask", "Bruno Tavares", "Elin Aas", "Gero Falk",
    "Nadia Cormier", "Rurik Salmela",
]

SENIORITIES = ["Principal Investigator", "Senior Investigator", "Staff Investigator"]

# Milestones: (trial_id, milestone_name, due_date, completed_date)
MILESTONES: list[tuple[str, str, str, str | None]] = [
    # Delayed (completed after due date) - the deliberate scenario signals
    ("T-2001", "First Patient In", "2024-05-01", "2024-06-20"),
    ("T-2005", "Database Lock", "2025-03-01", "2025-04-15"),
    ("T-2009", "Last Patient In", "2024-11-01", "2024-12-19"),
    # Pending (no completion date) - not delayed, but not on-time either
    ("T-2003", "Database Lock", "2025-09-01", None),
    # On-time milestones
    ("T-2001", "Last Patient In", "2025-06-01", "2025-05-12"),
    ("T-2001", "Database Lock", "2025-11-01", "2025-10-04"),
    ("T-2002", "First Patient In", "2023-11-01", "2023-10-21"),
    ("T-2002", "Last Patient In", "2025-08-01", "2025-07-15"),
    ("T-2003", "First Patient In", "2024-04-01", "2024-03-18"),
    ("T-2003", "Last Patient In", "2025-04-01", "2025-03-27"),
    ("T-2004", "First Patient In", "2023-07-01", "2023-06-19"),
    ("T-2004", "Last Patient In", "2024-10-01", "2024-09-20"),
    ("T-2004", "Database Lock", "2025-01-01", "2024-12-11"),
    ("T-2005", "First Patient In", "2024-03-01", "2024-02-22"),
    ("T-2005", "Last Patient In", "2025-02-01", "2025-01-24"),
    ("T-2006", "First Patient In", "2024-01-01", "2023-12-15"),
    ("T-2006", "Last Patient In", "2025-10-01", "2025-09-18"),
    ("T-2007", "First Patient In", "2023-09-01", "2023-08-25"),
    ("T-2007", "Last Patient In", "2025-01-01", "2024-12-10"),
    ("T-2008", "First Patient In", "2024-08-01", "2024-07-19"),
    ("T-2008", "Last Patient In", "2025-09-01", "2025-08-21"),
    ("T-2009", "First Patient In", "2024-05-01", "2024-04-26"),
    ("T-2009", "Database Lock", "2025-04-01", "2025-03-14"),
    ("T-2010", "First Patient In", "2023-10-01", "2023-09-22"),
    ("T-2010", "Last Patient In", "2025-07-01", "2025-06-13"),
    ("T-2010", "Database Lock", "2026-01-01", "2025-12-09"),
]

# Operational safety/quality events. Deliberately operational in nature -
# no medical outcomes, no patient-level data.
SAFETY_EVENTS: list[tuple[str, str, str, str | None, str, str, str]] = [
    # id, site_id, trial_id, compound_id, severity, reported_at, description
    ("SE-11001", "S-1001", "T-2001", "C-5001", "HIGH", "2024-08-14",
     "Compound storage temperature excursion above the permitted range"),
    ("SE-11002", "S-1001", "T-2001", None, "HIGH", "2024-10-02",
     "Recurring site staff shortage during scheduled dosing visits"),
    ("SE-11003", "S-1001", "T-2001", None, "MEDIUM", "2024-11-19",
     "Sample shipment delay exceeding the stability window"),
    ("SE-11004", "S-1001", "T-2001", None, "HIGH", "2025-01-07",
     "Device calibration drift affecting primary endpoint capture"),
    ("SE-11005", "S-1001", "T-2001", None, "LOW", "2025-02-25",
     "Data capture system outage during a scheduled visit window"),
    ("SE-11006", "S-1004", "T-2001", None, "LOW", "2025-01-21",
     "Visitor access badge lapse in the restricted storage area"),
    ("SE-11007", "S-1006", "T-2002", None, "MEDIUM", "2024-09-30",
     "Refrigerated sample relay stopped overnight"),
    ("SE-11008", "S-1011", "T-2003", "C-5004", "HIGH", "2025-03-11",
     "Site power interruption during a stability chamber cycle"),
    ("SE-11009", "S-1013", "T-2003", None, "HIGH", "2025-02-05",
     "Monitoring visit found repeated protocol deviation patterns"),
]

INVESTIGATOR_SITE_ASSIGNMENT: dict[str, list[str]] = {
    "S-1001": ["I-7001", "I-7002"],
    "S-1002": ["I-7003", "I-7004", "I-7005"],
    "S-1003": ["I-7006"],
    "S-1004": ["I-7007", "I-7008"],
    "S-1005": ["I-7009", "I-7010"],
    "S-1006": ["I-7011"],
    "S-1007": ["I-7012", "I-7013"],
    "S-1008": ["I-7014", "I-7015"],
    "S-1009": ["I-7016"],
    "S-1010": ["I-7017", "I-7018"],
    "S-1011": ["I-7019"],
    "S-1012": ["I-7020"],
    "S-1013": ["I-7021"],
    "S-1014": ["I-7022"],
    "S-1015": ["I-7023", "I-7024"],
    "S-1016": ["I-7025"],
    "S-1017": ["I-7026", "I-7027"],
    "S-1018": ["I-7028"],
    "S-1019": ["I-7029"],
    "S-1020": ["I-7030"],
}

# Capacity slope per region (capacity_index change per month)
CAPACITY_TREND: dict[str, float] = {
    "R-01": 0.007,   # Nordic: slightly rising (distractor)
    "R-02": -0.031,  # Western Europe: DECLINING capacity while enrolment rises
    "R-03": 0.000,   # Central Europe: flat
    "R-04": 0.000,   # Iberian: flat (and enrolment declining anyway)
    "R-05": 0.021,   # North Atlantic: rising (distractor: both rise)
    "R-06": 0.000,   # Baltic: flat
}


@dataclass
class EntityRec:
    id: str
    type: str
    name: str
    description: str


@dataclass
class GeneratedDocument:
    doc_id: str
    title: str
    filename: str
    content_type: str
    document_date: str
    mentions: list[str] = field(default_factory=list)
    adversarial: bool = False
    text: str = ""
    pdf_text: str | None = None  # when set, render as PDF with this text


@dataclass
class Corpus:
    entities: list[EntityRec] = field(default_factory=list)
    relationships: list[tuple[str, str, str]] = field(default_factory=list)  # src, dst, rel
    aliases: dict[str, str] = field(default_factory=dict)
    tables: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    documents: list[GeneratedDocument] = field(default_factory=list)


def _site_pattern(site_id: str) -> str:
    return next(s[4] for s in SITES if s[0] == site_id)


def _country_region(country_id: str) -> str:
    return next(c[2] for c in COUNTRIES if c[0] == country_id)


def _series(rng: Random, pattern: str, scale: float = 1.0) -> list[tuple[int, int]]:
    """Monthly (patients_enrolled, operational_cost) series for a pattern."""
    e_start, e_slope, c_start, c_slope = METRIC_PATTERNS[pattern]
    rows: list[tuple[int, int]] = []
    for i in range(len(MONTHS)):
        enrolled = e_start + e_slope * i + rng.uniform(-1.2, 1.2)
        cost = (c_start + c_slope * i) * scale + rng.uniform(-2_200, 2_200)
        rows.append((max(0, round(enrolled)), round(cost)))
    return rows


def build_corpus(seed: int = 42) -> Corpus:
    rng = Random(seed)
    corpus = Corpus()

    # ---- geography / organisations -------------------------------------
    for rid, name in REGIONS:
        corpus.entities.append(EntityRec(f"region:{rid}", "region", name,
                                         f"Synthetic operating region {name}."))
    for cid, name, rid in COUNTRIES:
        corpus.entities.append(EntityRec(f"country:{cid}", "country", name,
                                         f"Synthetic country {name} in region {rid}."))
        corpus.relationships.append((f"country:{cid}", f"region:{rid}", "COUNTRY_IN_REGION"))
    for hid, name, cid in HOSPITALS:
        corpus.entities.append(EntityRec(f"hospital:{hid}", "hospital", name,
                                         f"Synthetic hospital {name} in country {cid}."))
        corpus.relationships.append((f"hospital:{hid}", f"country:{cid}", "HOSPITAL_LOCATED_IN"))
    for coid, name, hq in COMPANIES:
        corpus.entities.append(EntityRec(
            f"company:{coid}", "company", name,
            f"Synthetic pharmaceutical company headquartered in {hq}."))
    for cid, name, target in COMPOUNDS:
        corpus.entities.append(EntityRec(
            f"compound:{cid}", "compound", name,
            f"Synthetic investigational compound {name} (fictional target: {target})."))
    for pid, name, coid, comp in PRODUCTS:
        corpus.entities.append(EntityRec(
            f"product:{pid}", "product", name,
            f"Synthetic therapeutic product {name} by {coid}, derived from {comp}."))
        corpus.relationships.append((f"company:{coid}", f"product:{pid}", "COMPANY_OWNS_PRODUCT"))
        corpus.relationships.append((f"product:{pid}", f"compound:{comp}", "PRODUCT_DERIVED_FROM"))
        corpus.relationships.append((f"compound:{comp}", f"product:{pid}",
                                     "COMPOUND_RELATED_TO_PRODUCT"))

    # ---- trials / milestones / safety events ---------------------------
    for tid, codename, phase, coid, status in TRIALS:
        start, end = TRIAL_DATES[tid]
        corpus.entities.append(EntityRec(
            f"trial:{tid}", "trial", codename,
            f"Synthetic clinical trial {codename} ({phase}) sponsored by {coid}."))
        corpus.relationships.append((f"company:{coid}", f"trial:{tid}", "COMPANY_SPONSORS_TRIAL"))
        for comp in TRIAL_COMPOUNDS[tid]:
            corpus.relationships.append((f"trial:{tid}", f"compound:{comp}", "TRIAL_USES_COMPOUND"))
        corpus.tables.setdefault("trials", []).append({
            "trial_id": tid, "codename": codename, "phase": phase, "company_id": coid,
            "status": status, "start_date": start, "planned_end_date": end,
        })
    for tid, name, due, completed in MILESTONES:
        mid = f"M-{3001 + MILESTONES.index((tid, name, due, completed))}"
        corpus.entities.append(EntityRec(
            f"milestone:{mid}", "milestone", f"{name} ({tid})",
            f"Milestone {name} of trial {tid} (due {due})."))
        corpus.relationships.append((f"trial:{tid}", f"milestone:{mid}", "TRIAL_HAS_MILESTONE"))
        corpus.tables.setdefault("milestones", []).append({
            "milestone_id": mid, "trial_id": tid, "name": name,
            "due_date": due, "completed_date": completed,
        })
    for eid, sid, tid, comp_opt, severity, reported, desc in SAFETY_EVENTS:
        corpus.entities.append(EntityRec(
            f"safetyevent:{eid}", "safetyevent", eid,
            f"Operational safety event at {sid}: {desc} (severity {severity})."))
        corpus.relationships.append((f"trial:{tid}", f"safetyevent:{eid}",
                                     "TRIAL_REPORTS_SAFETY_EVENT"))
        corpus.relationships.append((f"safetyevent:{eid}", f"site:{sid}", "SAFETY_EVENT_AT_SITE"))
        if comp_opt:
            corpus.relationships.append((f"safetyevent:{eid}", f"compound:{comp_opt}",
                                         "SAFETY_EVENT_INVOLVES_COMPOUND"))
        corpus.tables.setdefault("safety_events", []).append({
            "event_id": eid, "site_id": sid, "trial_id": tid,
            "compound_id": comp_opt or "",
            "severity": severity, "reported_at": reported, "description": desc,
        })

    # ---- sites ----------------------------------------------------------
    for sid, name, cid, host, _pattern in SITES:
        corpus.entities.append(EntityRec(
            f"site:{sid}", "site", name,
            f"Synthetic trial site in {cid}"
            + (f", hosted by {host}" if host else "") + "."))
        if host:
            corpus.relationships.append((f"site:{sid}", f"hospital:{hid}", "SITE_LOCATED_IN"))
        else:
            corpus.relationships.append((f"site:{sid}", f"country:{cid}", "SITE_LOCATED_IN"))
        corpus.tables.setdefault("sites", []).append({
            "site_id": sid, "name": name, "country_id": cid,
            "hospital_id": hid or "", "metric_pattern": _pattern,
        })

    for tid, sids in TRIAL_SITES.items():
        for sid in sids:
            corpus.relationships.append((f"trial:{tid}", f"site:{sid}", "TRIAL_HAS_SITE"))

    site_rows: list[dict[str, object]] = []
    for sid, _name, _cid, _hid, pattern in SITES:
        trials_for_site = [t for t, sids in TRIAL_SITES.items() if sid in sids]
        primary = trials_for_site[0]
        rows = _series(rng, pattern)
        for (trial, scale) in [(primary, 1.0)] + [
            (t, round(rng.uniform(0.35, 0.6), 2)) for t in trials_for_site[1:]
        ]:
            for i, month in enumerate(MONTHS):
                enrolled, cost = rows[i]
                site_rows.append({
                    "site_id": sid, "trial_id": trial, "month": month,
                    "patients_enrolled": max(0, round(enrolled * scale)),
                    "operational_cost": round(cost * scale),
                })
    corpus.tables["site_metrics_monthly"] = site_rows

    # ---- investigators + capacity ---------------------------------------
    site_country = {s[0]: s[2] for s in SITES}
    investigator_rows: list[dict[str, object]] = []
    name_i = 0
    for sid, investigators in INVESTIGATOR_SITE_ASSIGNMENT.items():
        for j, iid in enumerate(investigators):
            name = INVESTIGATOR_NAMES[name_i] if name_i < len(INVESTIGATOR_NAMES) \
                else f"Investigator {iid}"
            name_i += 1
            seniority = SENIORITIES[j % len(SENIORITIES)]
            corpus.entities.append(EntityRec(
                f"investigator:{iid}", "investigator", name,
                f"Synthetic {seniority} at site {sid}."))
            corpus.relationships.append((f"investigator:{iid}", f"site:{sid}",
                                         "INVESTIGATOR_WORKS_AT"))
            investigator_rows.append({
                "investigator_id": iid, "name": name, "site_id": sid, "seniority": seniority,
            })
    corpus.tables["investigators"] = investigator_rows
    cap_rows: list[dict[str, object]] = []
    for inv in investigator_rows:
        sid = str(inv["site_id"])
        region = _country_region(site_country[sid])
        slope = CAPACITY_TREND[region]
        base = 0.92 if slope < 0 else 0.70
        for i, month in enumerate(MONTHS):
            cap_rows.append({
                "investigator_id": inv["investigator_id"], "month": month,
                "capacity_index": round(max(0.1, min(1.0, base + slope * i
                                                     + rng.uniform(-0.02, 0.02))), 3),
            })
    corpus.tables["investigator_capacity_monthly"] = cap_rows

    # ---- region analytics marts (pre-joined for the single-table SQL tool)
    country_of_site = {s[0]: s[2] for s in SITES}
    region_of_country = {c[0]: c[2] for c in COUNTRIES}

    def region_of_site(site_id: str) -> str:
        return region_of_country[country_of_site[site_id]]

    region_metrics: dict[tuple[str, str], list[int]] = {}
    for row in site_rows:
        key = (region_of_site(str(row["site_id"])), str(row["month"]))
        totals = region_metrics.setdefault(key, [0, 0])
        totals[0] += int(str(row["patients_enrolled"]))
        totals[1] += int(str(row["operational_cost"]))
    corpus.tables["site_metrics_region_monthly"] = [
        {"region_id": region, "month": month, "total_patients_enrolled": totals[0],
         "total_operational_cost": totals[1]}
        for (region, month), totals in sorted(region_metrics.items())
    ]

    inv_region: dict[str, str] = {}
    for inv in investigator_rows:
        inv_region[str(inv["investigator_id"])] = region_of_site(str(inv["site_id"]))
    region_capacity: dict[tuple[str, str], list[float]] = {}
    for row in cap_rows:
        key = (inv_region[str(row["investigator_id"])], str(row["month"]))
        acc = region_capacity.setdefault(key, [0.0, 0])
        acc[0] += float(str(row["capacity_index"]))
        acc[1] += 1
    corpus.tables["investigator_capacity_region_monthly"] = [
        {"region_id": region, "month": month,
         "avg_capacity_index": round(acc[0] / acc[1], 4)}
        for (region, month), acc in sorted(region_capacity.items())
    ]

    # ---- aliases (used by extraction + name resolution) -------------------
    for e in corpus.entities:
        corpus.aliases[e.name] = e.id
    corpus.aliases["Site A"] = "site:S-1001"
    corpus.aliases["Site B"] = "site:S-1002"

    # ---- documents (rendered in synth.documents) -------------------------
    from nexusgraph.synth.documents import build_documents
    corpus.documents = build_documents()

    return corpus


def write_corpus(corpus: Corpus, out_dir: Path) -> dict[str, object]:
    """Materialise the corpus as CSVs, TTL, documents and a manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tables").mkdir(exist_ok=True)
    (out_dir / "documents").mkdir(exist_ok=True)

    def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
        if not rows:
            return
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    with (out_dir / "entities.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "type", "name", "description"])
        for e in sorted(corpus.entities, key=lambda x: x.id):
            writer.writerow([e.id, e.type, e.name, e.description])

    with (out_dir / "relationships.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["source_id", "target_id", "relation"])
        for src, dst, rel in sorted(corpus.relationships):
            writer.writerow([src, dst, rel])

    with (out_dir / "aliases.json").open("w", encoding="utf-8") as fh:
        json.dump(dict(sorted(corpus.aliases.items())), fh, indent=2, ensure_ascii=False)

    for table, rows in sorted(corpus.tables.items()):
        write_csv(out_dir / "tables" / f"{table}.csv", rows)

    index: list[dict[str, object]] = []
    for doc in sorted(corpus.documents, key=lambda d: d.doc_id):
        if doc.pdf_text is not None:
            from nexusgraph.synth.documents import render_pdf
            render_pdf(doc.pdf_text, out_dir / "documents" / doc.filename)
        else:
            (out_dir / "documents" / doc.filename).write_text(doc.text, encoding="utf-8")
        index.append({
            "doc_id": doc.doc_id, "title": doc.title, "filename": doc.filename,
            "content_type": doc.content_type, "document_date": doc.document_date,
            "mentions": doc.mentions, "adversarial": doc.adversarial,
        })
    with (out_dir / "documents_index.json").open("w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False)

    from nexusgraph.synth.rdf import build_data_graph, write_turtle
    ttl_path = out_dir / "graph.ttl"
    write_turtle(build_data_graph(corpus), ttl_path)

    manifest = {
        "seed": 42,
        "synthetic": True,
        "counts": {
            "entities": len(corpus.entities),
            "relationships": len(corpus.relationships),
            "documents": len(corpus.documents),
            "tables": {k: len(v) for k, v in sorted(corpus.tables.items())},
        },
        "expected_facts": {
            "declining_enrolment_rising_cost_sites": ["S-1001", "S-1007", "S-1013"],
            "trials_with_delayed_milestones": ["T-2001", "T-2005", "T-2009"],
            "products_linked_to_delayed_trials": ["P-4001", "P-4002", "P-4005", "P-4007"],
            "site_with_most_safety_events": "S-1001",
            "higher_risk_site_pair": {"higher": "S-1001", "lower": "S-1002"},
            "region_rising_enrolment_declining_capacity": "R-02",
            "region_rising_enrolment_declining_capacity_name": "Western Europe Cluster",
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
