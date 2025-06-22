from fastapi import WebSocket, WebSocketDisconnect

from healthchat.core.lib import FastApiRouter

router = FastApiRouter(
    prefix="/ws",
    tags=["websockets"]
)

@router.websocket("/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Message text was: {data}")
    except WebSocketDisconnect:
        print("Client disconnected")

