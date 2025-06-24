from fastapi import WebSocket, WebSocketDisconnect

from healthchat.agents.audio_agent import AudioAgent
from healthchat.core.lib import FastApiRouter


router = FastApiRouter(
    prefix="/ws",
    tags=["websockets"]
)

@router.websocket("/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()

    agent = AudioAgent(websocket)
    await agent.run()
