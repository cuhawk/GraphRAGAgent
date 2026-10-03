"""Entity resolution: alias surfaces -> canonical ids, obvious-duplicate merging."""

from __future__ import annotations

import re

from nexusgraph.domain.models import Entity

_PUNCT_RE = re.compile(r"[^a-z0-9]+")


def normalize_name(name: str) -> str:
    """Canonical form used for duplicate detection ('Nordhaven Univ. Hospital'
    and 'nordhaven university hospital' collapse to the same key)."""
    return _PUNCT_RE.sub(" ", name.lower()).strip()


class EntityResolver:
    """Maps text surfaces (names, aliases, codes) to canonical entity ids."""

    def __init__(self, aliases: dict[str, str] | None = None) -> None:
        self._surface_to_id: dict[str, str] = {}
        self._normalized_to_id: dict[str, str] = {}
        for surface, canonical in (aliases or {}).items():
            self.add(surface, canonical)

    def add(self, surface: str, canonical: str) -> None:
        self._surface_to_id[surface] = canonical
        key = normalize_name(surface)
        self._normalized_to_id.setdefault(key, canonical)

    def resolve(self, surface: str) -> str | None:
        return self._surface_to_id.get(surface) or self._normalized_to_id.get(
            normalize_name(surface)
        )

    def canonical_id(self, entity_id: str) -> str:
        """Idempotent: returns the canonical id for a surface or id."""
        return self.resolve(entity_id) or entity_id

    def known_entity_ids(self) -> set[str]:
        return set(self._surface_to_id.values())

    def surfaces(self) -> list[str]:
        return sorted(self._surface_to_id, key=len, reverse=True)

    @property
    def size(self) -> int:
        return len(self._surface_to_id)


def dedupe_entities(entities: list[Entity]) -> tuple[list[Entity], list[tuple[str, str]]]:
    """Merge entities whose normalised names collide (obvious duplicates).

    The lowest id wins; source_ids and attributes of duplicates are folded in.
    Returns ``(canonical_entities, merges)`` where merges is a list of
    ``(dropped_id, kept_id)``.
    """
    by_key: dict[tuple[str, str], Entity] = {}
    kept: list[Entity] = []
    merges: list[tuple[str, str]] = []
    for entity in sorted(entities, key=lambda e: e.id):
        key = (normalize_name(entity.name), entity.type)
        keeper = by_key.get(key)
        if keeper is None:
            by_key[key] = entity
            kept.append(entity)
            continue
        merges.append((entity.id, keeper.id))
        keeper.source_ids = sorted(set(keeper.source_ids) | set(entity.source_ids))
        for attr, value in entity.attributes.items():
            keeper.attributes.setdefault(attr, value)
        if not keeper.description and entity.description:
            keeper.description = entity.description
    return kept, merges
