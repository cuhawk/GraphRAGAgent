"""Question-time entity resolution: surface forms in the question -> entity ids.

Longest-surface-first matching over the entity name index (which includes the
synthetic corpus's aliases such as 'Site A' -> site:S-1001 and trial
codenames). Overlapping shorter matches inside a longer match are dropped.
"""

from __future__ import annotations

import re

from nexusgraph.domain.models import Entity
from nexusgraph.observability.logging import get_logger

logger = get_logger("agent.resolver")


class QuestionEntityResolver:
    def __init__(self, names: list[tuple[str, str]]) -> None:
        # names: (surface, entity_id)
        surfaces = sorted({n for n, _ in names}, key=len, reverse=True)
        id_by_surface: dict[str, str] = {}
        for surface, entity_id in names:
            id_by_surface.setdefault(surface, entity_id)
        self._id_by_surface = id_by_surface
        self._surface_re = re.compile(
            r"(?<![A-Za-z0-9])(" + "|".join(re.escape(s) for s in surfaces) +
            r")(?![A-Za-z0-9])", re.IGNORECASE) if surfaces else None

    def resolve(self, question: str) -> list[Entity]:
        if self._surface_re is None:
            return []
        found: dict[str, Entity] = {}
        occupied: list[tuple[int, int]] = []
        for match in self._surface_re.finditer(question):
            start, end = match.span()
            if any(s < end and start < e for s, e in occupied):
                continue  # inside an already-matched longer surface
            entity_id = self._id_by_surface.get(match.group(0)) \
                or next((eid for s, eid in self._id_by_surface.items()
                         if s.lower() == match.group(0).lower()), None)
            if entity_id is None:
                continue
            occupied.append((start, end))
            entity_type, _, local = entity_id.partition(":")
            found.setdefault(entity_id, Entity(
                id=entity_id, type=entity_type, name=match.group(0)))
        return sorted(found.values(), key=lambda e: len(e.name), reverse=True)
