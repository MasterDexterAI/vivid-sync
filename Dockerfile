FROM python:3.12-slim
WORKDIR /app
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt && pip install --no-cache-dir silero-vad --no-deps
COPY server ./server
COPY scripts ./scripts
COPY knowledge ./knowledge
RUN python scripts/fetch_vad_model.py
EXPOSE 8000
CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000} --ws-ping-interval 20"]
