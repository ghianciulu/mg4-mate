FROM python:3.12-slim

WORKDIR /app

# Build context is the project root (docker-compose: context: .)
COPY poller/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY poller/ /app/poller/

ENV PYTHONPATH=/app/poller
ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/poller/main.py"]
