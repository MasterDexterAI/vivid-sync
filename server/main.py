from fastapi import FastAPI, WebSocket

from .config import settings
from .session import CopilotSession

app = FastAPI(title="Vivid Sync")


@app.get("/health")
async def health():
    return {"ok": True, "model": settings.realtime_model, "key_loaded": bool(settings.openai_api_key)}


@app.websocket("/ws")
async def copilot_socket(ws: WebSocket):
    await ws.accept()
    session = CopilotSession(ws)
    try:
        await session.run()
    finally:
        await session.close()
