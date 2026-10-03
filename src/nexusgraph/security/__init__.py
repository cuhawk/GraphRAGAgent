"""Security layer: untrusted-query guards and resource limits.

The model never writes raw SQL (it fills a typed QuerySpec), and generated
SPARQL passes a strict guard. See docs/THREAT_MODEL.md.
"""

from nexusgraph.security.sparqlguard import SparqlGuardError, validate_sparql
from nexusgraph.security.sqlguard import SqlGuardError, validate_query_spec

__all__ = ["SparqlGuardError", "SqlGuardError", "validate_query_spec", "validate_sparql"]
