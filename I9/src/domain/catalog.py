"""
Catálogo de EPI publicado pelo A5 (artefato `PPE_CATALOG`).

O A5 anuncia o artefato em `ods.artifact.published` com `uri` e `hash_sha256`;
o conteúdo é lido pela `uri` e traz:

* `items`: cada EPI com `equipment_item` (id fixo do cadastro do A5, usado sem
  alteração na saída do I9), `name` (apenas exibição) e `class_aliases` (classes
  que o detector do I1 pode emitir para aquele EPI);
* `required`: por zona da aplicação, os itens exigidos. O I9 não sabe em que zona
  a pessoa está — isso é do S2 —, então avalia a **união** desses itens.

A zona do corpo de cada item (`body_part` no 6c) não vem do A5: é conhecimento
anatômico do I9, configurado em `item_zones` da política.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

ARTIFACT_PUBLISHED_SCHEMA = "ods.artifact.published"
PPE_CATALOG_KIND = "PPE_CATALOG"


def _require(data: Mapping[str, Any], key: str, context: str) -> Any:
    if key not in data:
        raise ValueError(f"{context}: campo obrigatório ausente -> {key!r}")
    return data[key]


@dataclass(frozen=True)
class ArtifactPublished:
    """Anúncio de artefato versionado (`ods.artifact.published`)."""

    artifact_id: str
    artifact_version: str
    kind: str
    owner: str
    uri: str
    hash_sha256: Optional[str]
    valid_from: str
    raw: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_event(cls, event: Mapping[str, Any]) -> "ArtifactPublished":
        schema = event.get("schema")
        if schema != ARTIFACT_PUBLISHED_SCHEMA:
            raise ValueError(
                f"schema inesperado: esperado {ARTIFACT_PUBLISHED_SCHEMA!r}, recebido {schema!r}"
            )
        payload = _require(event, "payload", "event")
        context = "artifact"
        hash_raw = payload.get("hash_sha256")
        return cls(
            artifact_id=str(_require(payload, "artifact_id", context)),
            artifact_version=str(_require(payload, "artifact_version", context)),
            kind=str(_require(payload, "kind", context)),
            owner=str(payload.get("owner", event.get("producer", ""))),
            uri=str(_require(payload, "uri", context)),
            hash_sha256=None if hash_raw is None else str(hash_raw).lower(),
            valid_from=str(payload.get("valid_from", "")),
            raw=dict(event),
        )


@dataclass(frozen=True)
class CatalogItem:
    equipment_item: str
    name: str
    class_aliases: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PpeCatalog:
    """Conteúdo de um `PPE_CATALOG` já validado."""

    artifact_id: str
    artifact_version: str
    items: Tuple[CatalogItem, ...]
    required_by_zone: Mapping[str, Tuple[str, ...]]

    def required_items(self) -> Tuple[str, ...]:
        """União dos itens exigidos em alguma zona, na ordem do catálogo."""
        exigidos = {item for items in self.required_by_zone.values() for item in items}
        return tuple(i.equipment_item for i in self.items if i.equipment_item in exigidos)

    @classmethod
    def from_content(
        cls, content: Mapping[str, Any], artifact_id: str = "", artifact_version: str = ""
    ) -> "PpeCatalog":
        context = "PPE_CATALOG"
        items_raw = _require(content, "items", context)
        if not isinstance(items_raw, list) or not items_raw:
            raise ValueError(f"{context}.items: esperado lista não vazia")

        items = []
        ids = set()
        for i, raw in enumerate(items_raw):
            ctx = f"{context}.items[{i}]"
            item_id = str(_require(raw, "equipment_item", ctx)).strip()
            if not item_id:
                raise ValueError(f"{ctx}: equipment_item vazio")
            if item_id in ids:
                raise ValueError(f"{ctx}: equipment_item duplicado {item_id!r}")
            ids.add(item_id)
            aliases = raw.get("class_aliases") or []
            if not isinstance(aliases, list):
                raise ValueError(f"{ctx}.class_aliases: esperado lista")
            items.append(
                CatalogItem(
                    equipment_item=item_id,
                    name=str(raw.get("name", item_id)),
                    class_aliases=tuple(str(a) for a in aliases),
                )
            )

        required: Dict[str, Tuple[str, ...]] = {}
        for i, raw in enumerate(content.get("required") or []):
            ctx = f"{context}.required[{i}]"
            zone_id = str(_require(raw, "zone_id", ctx))
            zone_items = tuple(str(x) for x in _require(raw, "items", ctx))
            desconhecidos = [x for x in zone_items if x not in ids]
            if desconhecidos:
                raise ValueError(f"{ctx}: itens fora do catálogo -> {desconhecidos}")
            required[zone_id] = zone_items

        return cls(
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            items=tuple(items),
            required_by_zone=required,
        )
