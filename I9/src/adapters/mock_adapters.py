from typing import Optional
from src.domain.models import (
    FrameContexto, RelacaoPessoaEPI, Pessoa, EPI, BoundingBox
)
import time

class MockIngestionAdapter:
    def __init__(self, max_frames: int = 3):
        self.max_frames = max_frames
        self.current_frame = 0

    def get_next_frame(self) -> Optional[FrameContexto]:
        if self.current_frame >= self.max_frames:
            return None
            
        self.current_frame += 1
        
        pessoa = Pessoa(
            id_rastreio=f"P_{self.current_frame}", 
            classe="pessoa", 
            confianca=0.98,
            bbox=BoundingBox(0.0, 0.0, 100.0, 100.0)
        )
        epi_capacete = EPI(
            id_rastreio=f"EPI_C_{self.current_frame}", 
            classe="capacete", 
            confianca=0.95,
            bbox=BoundingBox(10.0, 10.0, 30.0, 30.0)
        )
        epi_colete = EPI(
            id_rastreio=f"EPI_V_{self.current_frame}", 
            classe="colete", 
            confianca=0.90,
            bbox=BoundingBox(10.0, 40.0, 90.0, 90.0)
        )
        
        relacao = RelacaoPessoaEPI(pessoa=pessoa, epis=[epi_capacete, epi_colete])
        
        return FrameContexto(
            frame_id=f"frame_{self.current_frame}",
            timestamp=time.time(),
            pessoas_e_epis=[relacao]
        )

class MockConsoleOutputAdapter:
    def publish_event(self, frame_context: FrameContexto) -> None:
        print(f"\n--- Publicando Evento: {frame_context.frame_id} ---")
        for relacao in frame_context.pessoas_e_epis:
            print(f"Pessoa ID: {relacao.pessoa.id_rastreio}")
            for epi in relacao.epis:
                estado = epi.estado_relacional.name if epi.estado_relacional else "N/A"
                print(f"  -> EPI: {epi.classe} | Estado: {estado} | Confiança: {epi.confianca_relacional}")
        print("-" * 40)
