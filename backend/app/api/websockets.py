"""
Sentinel AI — WebSocket Manager
Manages real-time connections to the frontend dashboard.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List
import json
import structlog

log = structlog.get_logger()
router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        log.info("🔌 Client connected to WebSocket", active_count=len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            log.info("🔌 Client disconnected from WebSocket", active_count=len(self.active_connections))

    async def broadcast_incident_update(self, incident_data: dict):
        """Broadcast an incident status update to all connected clients."""
        if not self.active_connections:
            return
            
        message = {
            "type": "incident_update",
            "data": incident_data
        }
        
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                dead_connections.append(connection)
                
        # Clean up dead connections
        for dead in dead_connections:
            self.disconnect(dead)


# Singleton manager instance
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # We don't expect the client to send much, just keep connection alive
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        log.error("❌ WebSocket error", error=str(e))
        manager.disconnect(websocket)
