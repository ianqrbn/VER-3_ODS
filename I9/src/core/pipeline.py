from src.ports.ingestion_port import IngestionPort
from src.ports.output_port import OutputPort
from src.core.pairing import PairingModule
from src.core.inference import RelationInferenceModule

class I9Pipeline:
    def __init__(
        self,
        ingestion_port: IngestionPort,
        output_port: OutputPort,
        pairing_module: PairingModule,
        inference_module: RelationInferenceModule
    ):
        self.ingestion_port = ingestion_port
        self.output_port = output_port
        self.pairing_module = pairing_module
        self.inference_module = inference_module

    def run_once(self) -> bool:
        """
        Executa uma iteração do pipeline.
        Retorna True se processou um frame, False se não havia dados.
        """
        frame = self.ingestion_port.get_next_frame()
        if not frame:
            return False
            
        # O IngestionPort nesta simulação já retorna a entidade agrupada por facilidade,
        # Em um cenário real, se ele retornar detecções 'soltas', usaríamos o pairing_module aqui.
        
        for relacao in frame.pessoas_e_epis:
            self.inference_module.infer_states(relacao)
            
        self.output_port.publish_event(frame)
        return True
