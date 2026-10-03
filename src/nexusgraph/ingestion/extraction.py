"""Entity extraction.

- :class:`DeterministicExtractor` — the default: matches known entity
  surfaces (names/aliases) and well-formed dataset id tokens
  (``T-2001``, ``SE-11001``, ...) against the alias index. Zero cost, fully
  reproducible, and its output is exactly the provenance the citation layer
  needs for document-derived triples.

- :class:`LLMAssistedExtractor` — optional, for corpora without canonical
  names: the LLM proposes mentions, and every proposal is *validated against
  the resolver* — hallucinated entities are dropped, never stored.
"""

from __future__ import annotations

import re

from nexusgraph.config import LLMSettings
from nexusgraph.ingestion.resolution import EntityResolver
from nexusgraph.llm.base import ChatMessage, CompletionRequest, LLMClient, extract_json_object
from nexusgraph.observability.logging import get_logger

logger = get_logger("ingestion.extraction")

# Dataset id tokens, e.g. S-1001, T-2001, SE-11001, CO-8001, CT-101, R-02.
_ID_TOKEN_RE = re.compile(r"\b(SE|CO|CT|S|T|C|P|M|H|I|D|R)-(\d{2,5})\b")
_PREFIX_TO_TYPE: dict[str, str] = {
    "S": "site",
    "T": "trial",
    "C": "compound",
    "P": "product",
    "M": "milestone",
    "H": "hospital",
    "I": "investigator",
    "D": "document",
    "R": "region",
    "SE": "safetyevent",
    "CO": "company",
    "CT": "country",
}


class ExtractionResult:
    def __init__(self, entity_ids: list[str], method: str, llm_calls: int = 0) -> None:
        self.entity_ids = entity_ids
        self.method = method
        self.llm_calls = llm_calls


class DeterministicExtractor:
    def __init__(self, resolver: EntityResolver) -> None:
        self._resolver = resolver
        surfaces = resolver.surfaces()
        self._surface_re = (
            re.compile(
                r"(?<![A-Za-z0-9])("
                + "|".join(re.escape(s) for s in surfaces)
                + r")(?![A-Za-z0-9])"
            )
            if surfaces
            else None
        )
        self._ids = resolver.known_entity_ids()

    def extract(self, text: str) -> ExtractionResult:
        found: set[str] = set()
        if self._surface_re is not None:
            for match in self._surface_re.finditer(text):
                canonical = self._resolver.resolve(match.group(0))
                if canonical:
                    found.add(canonical)
        for match in _ID_TOKEN_RE.finditer(text):
            entity_id = f"{_PREFIX_TO_TYPE.get(match.group(1), '?')}:{match.group(0)}"
            if entity_id in self._ids:
                found.add(entity_id)
        return ExtractionResult(sorted(found), method="deterministic")


class LLMAssistedExtractor:
    """LLM proposes mentions; the resolver validates every one of them."""

    def __init__(
        self,
        llm: LLMClient,
        resolver: EntityResolver,
        settings: LLMSettings,
        max_chars: int = 6_000,
    ) -> None:
        self._llm = llm
        self._resolver = resolver
        self._settings = settings
        self._max_chars = max_chars
        self._fallback = DeterministicExtractor(resolver)

    def extract(self, text: str) -> ExtractionResult:
        valid_ids = self._resolver.known_entity_ids()
        catalog = "\n".join(sorted(valid_ids))
        prompt = (
            "You extract entity mentions from an enterprise document.\n"
            'Return ONLY a JSON object {"entities": ["<entity_id>", ...]} where\n'
            "each entity_id is copied VERBATIM from the catalog below and is "
            "explicitly mentioned in the text. Never invent ids. Empty list if none.\n\n"
            f"ENTITY CATALOG:\n{catalog}\n\nDOCUMENT:\n{text[: self._max_chars]}"
        )
        request = CompletionRequest(
            messages=[ChatMessage(role="user", content=prompt)],
            task="extract_entities",
            json_mode=True,
            temperature=0.0,
            max_tokens=512,
        )
        try:
            response = self._llm.complete(request)
            payload = extract_json_object(response.text)
            proposed = payload.get("entities", [])
            if not isinstance(proposed, list):
                raise ValueError("entities must be a list")
        except Exception as exc:
            logger.warning("LLM extraction failed (%s); falling back to deterministic", exc)
            return self._fallback.extract(text)

        validated = sorted({str(item) for item in proposed if item in valid_ids})
        # Union with deterministic matches so structured ids are never lost.
        deterministic = self._fallback.extract(text)
        merged = sorted(set(validated) | set(deterministic.entity_ids))
        return ExtractionResult(merged, method=f"llm-assisted({self._llm.model})", llm_calls=1)
