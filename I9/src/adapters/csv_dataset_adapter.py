"""
Adaptador de dataset em CSV para calibração das regras geométricas.

Formato esperado do CSV (uma linha por track):

    camera_id,frame,track_id,class,x_min,y_min,x_max,y_max,relational_state,homography
    CAM-01,1001,42,pessoa,412,268,668,1012,,,
    CAM-01,1001,101,capacete,468,884,612,1034,CORRETO,"[[...]]"
    CAM-01,1001,102,colete,430,346,650,546,INCORRETO,"[[...]]"

* ``relational_state`` é o ground truth (CORRETO/INCORRETO/AUSENTE) — vazio para pessoas.
* ``homografia`` é opcional (pode estar em coluna separada ou em arquivo auxiliar).
* Tracks são agrupadas por ``(camera_id, frame)`` para reconstruir ``TrackingFrame``.
"""

from __future__ import annotations

import csv
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


def _parse_bbox(row: Dict[str, str], context: str) -> Tuple[float, float, float, float]:
    try:
        x_min = float(row["x_min"])
        y_min = float(row["y_min"])
        x_max = float(row["x_max"])
        y_max = float(row["y_max"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"{context}: bbox inválida -> {exc}") from exc
    if x_max <= x_min or y_max <= y_min:
        raise ValueError(f"{context}: bbox inválida (max <= min)")
    return x_min, y_min, x_max, y_max


def _parse_homography(value: Optional[str]) -> Optional[List[List[float]]]:
    if not value or not value.strip():
        return None
    try:
        matrix = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"homografia inválida: {exc}") from exc
    if not isinstance(matrix, list) or len(matrix) != 3:
        raise ValueError("homografia: esperado array 3x3")
    if any(not isinstance(row, list) or len(row) != 3 for row in matrix):
        raise ValueError("homografia: esperado array 3x3")
    return matrix


class CsvDatasetAdapter:
    """Carrega dataset anotado de um arquivo CSV."""

    def load(self, path: str) -> List[AnnotatedFrame]:
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"dataset não encontrado: {path}")

        rows = self._read_csv(file_path)
        return self._group_by_frame(rows)

    def _read_csv(self, path: Path) -> List[Dict[str, str]]:
        with open(path, "r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            return list(reader)

    def _group_by_frame(self, rows: List[Dict[str, str]]) -> List[AnnotatedFrame]:
        grouped: Dict[Tuple[str, int], List[Dict[str, str]]] = defaultdict(list)
        for row in rows:
            camera_id = row["camera_id"]
            frame = int(row["frame"])
            grouped[(camera_id, frame)].append(row)

        frames: List[AnnotatedFrame] = []
        for (camera_id, frame_num), frame_rows in sorted(grouped.items()):
            tracks: List[AnnotatedTrack] = []
            homography: Optional[List[List[float]]] = None

            for i, row in enumerate(frame_rows):
                context = f"frame {frame_num}, track[{i}]"
                x_min, y_min, x_max, y_max = _parse_bbox(row, context)

                state_raw = row.get("relational_state", "").strip()
                state: Optional[RelationalState] = None
                if state_raw:
                    try:
                        state = RelationalState(state_raw.upper())
                    except ValueError:
                        raise ValueError(
                            f"{context}: relational_state inválido -> {state_raw!r}"
                        ) from None

                track = AnnotatedTrack(
                    track_id=int(row["track_id"]),
                    raw_class=row["class"],
                    x_min=x_min,
                    y_min=y_min,
                    x_max=x_max,
                    y_max=y_max,
                    relational_state=state,
                )
                tracks.append(track)

                # Homografia: pega a primeira não vazia
                if homography is None:
                    homography = _parse_homography(row.get("homography"))

            frame = AnnotatedFrame(
                camera_id=camera_id,
                frame=frame_num,
                tracks=tuple(tracks),
                homography=homography,
            )
            frames.append(frame)

        return frames
