"""
Leitura do `PPE_CATALOG` do A5.

Fluxo: `ods.artifact.published` (kind `PPE_CATALOG`) -> download do conteúdo pela
`uri` -> conferência do `hash_sha256` -> `PpeCatalog`.

URIs aceitas:

* `registry://<owner>/<artifact_id>/<n>` -> `GET {A5_REGISTRY_BASE_URL}/registro/<artifact_id>/<n>`;
* `http://...` / `https://...` -> lidas diretamente;
* `file://...` -> arquivo local (testes e demonstração).

O hash é conferido sobre os bytes recebidos e, se não bater, sobre o JSON
canônico (chaves ordenadas, sem espaços), já que o A5 ainda não fixou sobre qual
forma ele é calculado. Catálogo com hash divergente é rejeitado.
"""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.parse
import urllib.request
from typing import Any, Callable, List, Mapping, Optional, Tuple

from src.adapters.message_adapters import RawMessage, decode_message
from src.domain.catalog import PPE_CATALOG_KIND, ArtifactPublished, PpeCatalog

logger = logging.getLogger("i9.catalog")


def _canonical_json(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _unwrap_content(data: Any) -> Mapping[str, Any]:
    """Aceita o conteúdo puro ou envolvido em `content` pela API do registro."""
    if isinstance(data, Mapping) and "items" in data:
        return data
    if isinstance(data, Mapping) and isinstance(data.get("content"), Mapping):
        return data["content"]
    raise ValueError("PPE_CATALOG: conteúdo sem 'items'")


class RegistryClient:
    """Baixa o conteúdo de um artefato a partir da `uri` anunciada."""

    def __init__(
        self,
        base_url: str = "",
        timeout_s: float = 5.0,
        opener: Optional[Callable[..., Any]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._open = opener or urllib.request.urlopen

    def resolve(self, artifact: ArtifactPublished) -> str:
        parsed = urllib.parse.urlparse(artifact.uri)
        if parsed.scheme in ("http", "https", "file"):
            return artifact.uri
        if parsed.scheme == "registry":
            if not self.base_url:
                raise ValueError(
                    f"uri {artifact.uri!r} exige A5_REGISTRY_BASE_URL configurado"
                )
            partes = [p for p in parsed.path.split("/") if p]
            if len(partes) != 2:
                raise ValueError(f"uri de registro inesperada: {artifact.uri!r}")
            artifact_id, numero = partes
            return f"{self.base_url}/registro/{artifact_id}/{numero}"
        raise ValueError(f"esquema de uri não suportado: {artifact.uri!r}")

    def fetch(self, artifact: ArtifactPublished) -> bytes:
        url = self.resolve(artifact)
        with self._open(url, timeout=self.timeout_s) as response:
            return response.read()


class CatalogLoader:
    """Transforma anúncios `ods.artifact.published` em `PpeCatalog` verificados.

    Anúncios de outros tipos (ZONES, RULES, ROUTING...) ou de outro dono são
    ignorados. Falhas não interrompem o I9: ficam em `rejected` e a política em
    uso é mantida.
    """

    def __init__(self, client: RegistryClient, owner: str = "A5"):
        self.client = client
        self.owner = owner
        self.rejected: List[Tuple[Any, str]] = []

    def on_message(self, message: RawMessage) -> Optional[PpeCatalog]:
        try:
            artifact = ArtifactPublished.from_event(decode_message(message))
        except ValueError as exc:
            self._reject(message, str(exc))
            return None

        if artifact.kind != PPE_CATALOG_KIND:
            return None
        if self.owner and artifact.owner != self.owner:
            logger.info("PPE_CATALOG de %s ignorado (dono esperado: %s)", artifact.owner, self.owner)
            return None

        try:
            body = self.client.fetch(artifact)
            catalog = self.parse(artifact, body)
        except (OSError, ValueError) as exc:  # urllib.error.URLError herda de OSError
            self._reject(message, f"{artifact.artifact_version}: {exc}")
            return None

        logger.info(
            "PPE_CATALOG %s carregado: %d item(ns)",
            catalog.artifact_version, len(catalog.items),
        )
        return catalog

    @staticmethod
    def parse(artifact: ArtifactPublished, body: bytes) -> PpeCatalog:
        data = json.loads(body)
        if artifact.hash_sha256:
            hashes = {hashlib.sha256(body).hexdigest(), hashlib.sha256(_canonical_json(data)).hexdigest()}
            if artifact.hash_sha256 not in hashes:
                raise ValueError("hash_sha256 não confere com o conteúdo baixado")
        return PpeCatalog.from_content(
            _unwrap_content(data), artifact.artifact_id, artifact.artifact_version
        )

    def _reject(self, message: Any, reason: str) -> None:
        logger.warning("anúncio de artefato rejeitado: %s", reason)
        self.rejected.append((message, reason))
