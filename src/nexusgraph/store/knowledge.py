"""Entity + relationship store over SQL (the relational mirror of the RDF graph).

The RDF store answers SPARQL; this store answers the typed lookup tools and
backs entity resolution (canonical ids, aliases).
"""

from __future__ import annotations

from sqlalchemy import Engine, func, or_, select
from sqlalchemy.orm import Session

from nexusgraph.db.orm import EntityRow, RelationshipRow
from nexusgraph.domain.models import Entity, EntityDetail, Relationship


class EntityStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ----------------------------------------------------------------- write
    def upsert_entities(self, entities: list[Entity]) -> None:
        with Session(self._engine) as session:
            for entity in entities:
                row = session.get(EntityRow, entity.id)
                if row is None:
                    row = EntityRow(id=entity.id)
                    session.add(row)
                row.type = entity.type
                row.name = entity.name
                row.description = entity.description
                row.attributes = entity.attributes
                row.source_ids = entity.source_ids
            session.commit()

    def upsert_relationships(self, relationships: list[Relationship]) -> None:
        with Session(self._engine) as session:
            for rel in relationships:
                exists = session.execute(
                    select(RelationshipRow.id)
                    .where(
                        RelationshipRow.source_id == rel.source_id,
                        RelationshipRow.target_id == rel.target_id,
                        RelationshipRow.relation == rel.relation,
                    )
                    .limit(1)
                ).scalar()
                if exists is None:
                    session.add(
                        RelationshipRow(
                            source_id=rel.source_id,
                            target_id=rel.target_id,
                            relation=rel.relation,
                            properties=rel.properties,
                            source_ids=rel.source_ids,
                        )
                    )
            session.commit()

    # ------------------------------------------------------------------ read
    def get_entity(self, entity_id: str) -> Entity | None:
        with Session(self._engine) as session:
            row = session.get(EntityRow, entity_id)
            return self._entity_from_row(row) if row else None

    def get_entity_detail(self, entity_id: str) -> EntityDetail | None:
        entity = self.get_entity(entity_id)
        if entity is None:
            return None
        return EntityDetail(entity=entity, relationships=self.get_relationships(entity_id))

    def get_relationships(
        self,
        entity_id: str,
        relation: str | None = None,
    ) -> list[Relationship]:
        with Session(self._engine) as session:
            query = select(RelationshipRow).where(
                or_(RelationshipRow.source_id == entity_id, RelationshipRow.target_id == entity_id)
            )
            if relation:
                query = query.where(RelationshipRow.relation == relation)
            rows = session.execute(query).scalars().all()
        return [self._rel_from_row(r) for r in rows]

    def find_entities(
        self, q: str | None = None, entity_type: str | None = None, limit: int = 25
    ) -> list[Entity]:
        with Session(self._engine) as session:
            query = select(EntityRow)
            if q:
                like = f"%{q}%"
                query = query.where(or_(EntityRow.name.ilike(like), EntityRow.id.ilike(like)))
            if entity_type:
                query = query.where(EntityRow.type == entity_type)
            rows = session.execute(query.order_by(EntityRow.id).limit(limit)).scalars().all()
        return [self._entity_from_row(r) for r in rows]

    def all_names(self, limit: int = 500) -> list[tuple[str, str]]:
        """(name, id) pairs for the agent's question-time entity resolver."""
        with Session(self._engine) as session:
            rows = session.execute(
                select(EntityRow.name, EntityRow.id)
                .where(
                    EntityRow.type.in_(
                        [
                            "trial",
                            "site",
                            "compound",
                            "product",
                            "company",
                            "region",
                            "country",
                            "hospital",
                            "investigator",
                            "safetyevent",
                            "milestone",
                        ]
                    )
                )
                .order_by(EntityRow.id)
                .limit(limit)
            ).all()
        return [(str(r[0]), str(r[1])) for r in rows]

    def count(self) -> int:
        with Session(self._engine) as session:
            return int(session.scalar(select(func.count()).select_from(EntityRow)) or 0)

    @staticmethod
    def _entity_from_row(row: EntityRow) -> Entity:
        return Entity(
            id=row.id,
            type=row.type,
            name=row.name,
            description=row.description,
            attributes=row.attributes or {},
            source_ids=row.source_ids or [],
        )

    @staticmethod
    def _rel_from_row(row: RelationshipRow) -> Relationship:
        return Relationship(
            source_id=row.source_id,
            target_id=row.target_id,
            relation=row.relation,
            properties=row.properties or {},
            source_ids=row.source_ids or [],
        )
