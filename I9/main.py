from src.adapters.mock_adapters import MockIngestionAdapter, MockConsoleOutputAdapter
from src.core.pairing import PairingModule
from src.core.inference import RelationInferenceModule
from src.core.pipeline import I9Pipeline

def main():
    print("Iniciando Componente I9...")
    
    # Inicializa os adaptadores (Mocks)
    ingestion = MockIngestionAdapter(max_frames=2)
    output = MockConsoleOutputAdapter()
    
    # Inicializa os módulos core
    pairing = PairingModule()
    inference = RelationInferenceModule()
    
    # Injeta as dependências no Pipeline (DIP)
    pipeline = I9Pipeline(
        ingestion_port=ingestion,
        output_port=output,
        pairing_module=pairing,
        inference_module=inference
    )
    
    # Roda o pipeline até esgotar os frames simulados
    while True:
        tem_dado = pipeline.run_once()
        if not tem_dado:
            break
            
    print("Processamento concluído.")

if __name__ == "__main__":
    main()
