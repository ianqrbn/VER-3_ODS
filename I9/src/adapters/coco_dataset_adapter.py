"""
Adaptador de dataset COCO JSON (Roboflow) para calibração das regras geométricas.

Formato COCO:
  - bbox = [x, y, width, height] com origem no canto superior esquerdo
  - Agrupado por image_id

Mapeamento de categorias:
  - "Safe Worker" -> pessoa com ground truth CORRETO
  - "Unsafe Worker" -> pessoa com ground truth INCORRETO (equipamento presente mas no lugar errado, ou ausente)
  - "Worker -only hat-" -> pessoa com ground truth INCORRETO (capacete OK, colete AUSENTE)
  - "Worker -only vest-" -> pessoa com ground truth INCORRETO (capacete AUSENTE, colete OK)
  - "hardhat" -> equipamento (capacete)
  - "vest" -> equipamento (colete)
  - "PPE2-PPE" -> ignorar (supercategoria)

Prioridade quando múltiplas classes de worker:
  1. Unsafe Worker (maior prioridade)
  2. Worker -only hat-
  3. Worker -only vest-
  4. Safe Worker (menor prioridade)
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.domain.models import (
    AnnotatedFrame,
    AnnotatedTrack,
    RelationalState,
    TrackingFrame,
    utc_now_iso,
)


# Mapeamento de categorias COCO para domínio I9
WORKER_CATEGORIES = {"Safe Worker", "Unsafe Worker", "Worker -only hat-", "Worker -only vest-"}
EQUIPMENT_CATEGORIES = {"hardhat", "vest"}
IGNORED_CATEGORIES = {"PPE2-PPE"}

# Prioridade de classes de worker (maior número = maior prioridade)
WORKER_PRIORITY = {
    "Unsafe Worker": 4,
    "Worker -only hat-": 3,
    "Worker -only vest-": 2,
    "Safe Worker": 1,
}


def _coco_bbox_to_i2_bbox(
    bbox: List[float], image_height: int
) -> Tuple[float, float, float, float]:
    """Converte bbox COCO para formato I2.

    COCO: [x, y, width, height] - origem top-left
    I2: (x_min, y_min, x_max, y_max) - origem bottom-left
    """
    x, y, width, height = bbox
    x_min = x
    y_min = image_height - (y + height)
    x_max = x + width
    y_max = image_height - y
    return x_min, y_min, x_max, y_max


class CocoDatasetAdapter:
    """Carrega dataset COCO JSON (Roboflow) e converte para AnnotatedFrame."""

    def load(self, path: str, split: str = "train") -> List[AnnotatedFrame]:
        """Carrega dataset COCO e retorna frames anotados.

        Args:
            path: caminho para o diretório do dataset (ex: "PPE detection.f.v9i.coco")
            split: subconjunto a carregar ("train", "valid" ou "test")

        Returns:
            Lista de AnnotatedFrame com ground truth
        """
        dataset_path = Path(path)
        if not dataset_path.exists():
            raise FileNotFoundError(f"dataset não encontrado: {path}")

        annotations_file = dataset_path / split / "_annotations.coco.json"
        if not annotations_file.exists():
            raise FileNotFoundError(f"arquivo de anotações não encontrado: {annotations_file}")

        with open(annotations_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        return self._parse_coco(data)

    def _parse_coco(self, data: Dict[str, Any]) -> List[AnnotatedFrame]:
        """Interpreta o JSON COCO e cria frames anotados."""
        # Mapeia categorias
        cat_map = {cat["id"]: cat["name"] for cat in data["categories"]}

        # Mapeia imagens
        img_map = {img["id"]: img for img in data["images"]}

        # Agrupa anotações por imagem
        by_image: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for ann in data["annotations"]:
            by_image[ann["image_id"]].append(ann)

        frames: List[AnnotatedFrame] = []

        for img_id, anns in sorted(by_image.items()):
            img = img_map[img_id]
            image_height = img["height"]
            image_width = img["width"]

            # Determina classe de worker (prioridade: Unsafe > only hat > only vest > Safe)
            worker_class = self._determine_worker_class(anns, cat_map)
            if worker_class is None:
                # Imagem sem worker - ignorar (não tem ground truth de pessoa)
                continue

            # Cria tracks anotadas
            tracks: List[AnnotatedTrack] = []

            for ann in anns:
                cat_name = cat_map.get(ann["category_id"], "")
                if cat_name in IGNORED_CATEGORIES:
                    continue

                x_min, y_min, x_max, y_max = _coco_bbox_to_i2_bbox(ann["bbox"], image_height)

                # Determina ground truth baseado na classe de worker e categoria
                gt_state = self._infer_ground_truth(worker_class, cat_name, anns, cat_map)

                track = AnnotatedTrack(
                    track_id=ann["id"],
                    raw_class=cat_name,
                    x_min=x_min,
                    y_min=y_min,
                    x_max=x_max,
                    y_max=y_max,
                    relational_state=gt_state,
                )
                tracks.append(track)

            if not tracks:
                continue

            frame = AnnotatedFrame(
                camera_id="coco",
                frame=img_id,
                tracks=tuple(tracks),
                homography=None,
            )
            frames.append(frame)

        return frames

    def _determine_worker_class(
        self, anns: List[Dict[str, Any]], cat_map: Dict[int, str]
    ) -> Optional[str]:
        """Determina a classe de worker com base na prioridade.

        Retorna None se não há classe de worker na imagem.
        """
        worker_classes = set()
        for ann in anns:
            cat_name = cat_map.get(ann["category_id"], "")
            if cat_name in WORKER_CATEGORIES:
                worker_classes.add(cat_name)

        if not worker_classes:
            return None

        # Retorna a classe com maior prioridade
        return max(worker_classes, key=lambda c: WORKER_PRIORITY.get(c, 0))

    def _infer_ground_truth(
        self,
        worker_class: str,
        cat_name: str,
        anns: List[Dict[str, Any]],
        cat_map: Dict[int, str],
    ) -> Optional[RelationalState]:
        """Infere o ground truth de uma track baseado na classe de worker.

        Returns:
            RelationalState ou None (para equipamentos, que não têm ground truth direto)
        """
        # Equipamentos não têm ground truth direto
        if cat_name in EQUIPMENT_CATEGORIES:
            return None

        # Para workers, o ground truth é inferido baseado na classe
        # Mas o ground truth real é por pessoa×EPI, não por worker
        # Vou retornar None para workers também, pois o ground truth será
        # inferido no EvaluationModule baseado na presença/ausência de equipamentos
        return None

    def _build_gt_map_for_frame(
        self, frame: AnnotatedFrame
    ) -> Dict[Tuple[int, str], RelationalState]:
        """Constrói mapa de ground truth para um frame.

        Mapeia (person_track_id, canonical_class) -> RelationalState
        """
        # Separa workers e equipamentos
        workers = [t for t in frame.tracks if t.raw_class in WORKER_CATEGORIES]
        equipments = [t for t in frame.tracks if t.raw_class in EQUIPMENT_CATEGORIES]

        if not workers:
            return {}

        # Determina classe de worker (prioridade)
        worker_class = max(workers, key=lambda w: WORKER_PRIORITY.get(w.raw_class, 0)).raw_class

        # Mapeia equipamentos por classe
        equipment_by_class: Dict[str, List[AnnotatedTrack]] = defaultdict(list)
        for eq in equipments:
            if eq.raw_class == "hardhat":
                equipment_by_class["CAPACETES"].append(eq)
            elif eq.raw_class == "vest":
                equipment_by_class["COLETES"].append(eq)

        # Infer ground truth para cada worker
        result: Dict[Tuple[int, str], RelationalState] = {}

        for worker in workers:
            for canonical_class in ["CAPACETES", "COLETES"]:
                has_equipment = len(equipment_by_class[canonical_class]) > 0

                if worker_class == "Unsafe Worker":
                    # Unsafe Worker: equipamento presente -> INCORRETO, ausente -> AUSENTE
                    if has_equipment:
                        result[(worker.track_id, canonical_class)] = RelationalState.INCORRETO
                    else:
                        result[(worker.track_id, canonical_class)] = RelationalState.AUSENTE

                elif worker_class == "Worker -only hat-":
                    # Só com capacete: capacete CORRETO, colete AUSENTE
                    if canonical_class == "CAPACETES":
                        result[(worker.track_id, canonical_class)] = RelationalState.CORRETO if has_equipment else RelationalState.AUSENTE
                    else:
                        result[(worker.track_id, canonical_class)] = RelationalState.AUSENTE

                elif worker_class == "Worker -only vest-":
                    # Só com colete: capacete AUSENTE, colete CORRETO
                    if canonical_class == "COLETES":
                        result[(worker.track_id, canonical_class)] = RelationalState.CORRETO if has_equipment else RelationalState.AUSENTE
                    else:
                        result[(worker.track_id, canonical_class)] = RelationalState.AUSENTE

                elif worker_class == "Safe Worker":
                    # Safe Worker: equipamento presente -> CORRETO, ausente -> AUSENTE
                    if has_equipment:
                        result[(worker.track_id, canonical_class)] = RelationalState.CORRETO
                    else:
                        result[(worker.track_id, canonical_class)] = RelationalState.AUSENTE

        return result
