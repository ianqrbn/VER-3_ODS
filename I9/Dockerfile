# Imagem do serviço contínuo do I9 no Kafka (`python3 main.py --kafka`).
# O broker vem de KAFKA_BOOTSTRAP_SERVERS (no docker-compose: kafka:29092).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements-kafka.txt .
RUN pip install --no-cache-dir -r requirements-kafka.txt

COPY . .

USER nobody

# forma exec: o Python é o PID 1 e recebe o SIGTERM do `docker stop`
CMD ["python3", "main.py", "--kafka"]
