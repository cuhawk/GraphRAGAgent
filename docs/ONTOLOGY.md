# Ontology

The RDF data model lives in [`ontology/nexusgraph.ttl`](../ontology/nexusgraph.ttl)
(OWL 2, Turtle). All data is synthetic; namespaces use `https://nexusgraph.dev/…`.

## Namespaces

| Prefix | IRI | Contents |
| --- | --- | --- |
| `ngx` | `https://nexusgraph.dev/ontology#` | classes, object/datatype properties |
| `nxg` | `https://nexusgraph.dev/data/…` | instance data, one sub-path per entity type |
| `graph` | `https://nexusgraph.dev/graph/document/<id>` | per-document named graph (mention triples) |

## Classes

`Company`, `Compound`, `Product`, `Trial`, `Site`, `Hospital`, `Country`,
`Region`, `Investigator`, `Milestone`, `SafetyEvent`, `ResearchDocument`.

All classes carry `ngx:name`; most have `ngx:description`. Domain-specific
datatype properties:

- `Trial`: `inPhase`, `status`, `startDate`, `plannedEndDate`
- `Milestone`: `dueDate`, `completedDate` (delay = completed > due)
- `SafetyEvent`: `severity` (`LOW|HIGH|MEDIUM`), `reportedAt`
- `ResearchDocument`: `title`, `contentType`, `documentDate`

## Object properties (relations)

| Property | Domain → range |
| --- | --- |
| `COMPANY_OWNS_PRODUCT` | Company → Product |
| `PRODUCT_DERIVED_FROM` | Product → Compound |
| `COMPOUND_RELATED_TO_PRODUCT` | Compound → Product (inverse) |
| `TRIAL_USES_COMPOUND` | Trial → Compound |
| `TRIAL_HAS_SITE` | Trial → Site |
| `TRIAL_REPORTS_SAFETY_EVENT` | Trial → SafetyEvent |
| `SAFETY_EVENT_AT_SITE` | SafetyEvent → Site |
| `SAFETY_EVENT_INVOLVES_COMPOUND` | SafetyEvent → Compound |
| `TRIAL_HAS_MILESTONE` | Trial → Milestone |
| `INVESTIGATOR_WORKS_AT_SITE` | Investigator → Site |
| `SITE_LOCATED_IN_COUNTRY` | Site → Country |
| `SITE_HOSTED_BY_HOSPITAL` | Site → Hospital |
| `HOSPITAL_LOCATED_IN` | Hospital → Country |
| `COUNTRY_IN_REGION` | Country → Region |
| `COMPANY_HEADQUARTERED_IN` | Company → Country |
| `DOCUMENT_MENTIONS` | ResearchDocument → any entity |

## Graph structure and provenance

- The **default graph** holds entity/relationship/attribute triples generated
  from the corpus.
- Each document gets a **named graph**
  (`https://nexusgraph.dev/graph/document/<doc-id>`) containing its
  `rdf:type ResearchDocument` definition and every `DOCUMENT_MENTIONS` triple
  derived from its text. Default-graph queries therefore do not see mention
  triples; queries that reason over mentions opt in with
  `use_default_graph_as_union` (the tool arg `include_named_graphs`). This
  makes the provenance of every mention explicit at the graph level and is
  also a privacy boundary (see docs/THREAT_MODEL.md §T3/T2).

## Instance IRIs

Entity ids like `site:S-1001` map to IRIs
`https://nexusgraph.dev/data/Site/S-1001` (`domain/ids.py` is the single
place this mapping lives).

## Relationship to the relational schema

The same corpus populates typed SQL tables (`store/structured.py` — 15 tables,
including the regional analytics marts). Graph and SQL are views of one
dataset; the agent crosses the boundary per question (mixed questions join
graph results with metric rows in the evidence ledger).
