"""
Sentinel AI — WebSocket Manager

Real-time incident updates to the dashboard, scoped per tenant.

Each connection is authenticated during the handshake against the same Clerk
session JWT the REST API uses, and registered under the caller's tenant
(``org_id``). ``broadcast_incident_update`` fans out only to connections that
belong to the incident's tenant, so one tenant never sees another's incidents.
"""

from collections import defaultdict
from typing import Dict, Optional, Set
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from jose.exceptions import JWTError

from app.auth.clerk import get_verifier

log = structlog.get_logger()
router = APIRouter()


def _tenant_from_token(token: str) -> Optional[str]:
    """Verify a Clerk session JWT and return its tenant (org) id, or None."""
    if not token:
        return None
    try:
        claims = get_verifier().verify(token)
    except (JWTError, Exception):  # verify() raises HTTPException on bad tokens
        return None
    org_id = claims.get("org_id")
    if not org_id:
        o = claims.get("o")
        if isinstance(o, dict):
            org_id = o.get("id")
    return org_id or None


class ConnectionManager:
    def __init__(self):
        # tenant_id -> set of live sockets
        self.by_tenant: Dict[str, Set[WebSocket]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, tenant_id: str):
        await websocket.accept()
        self.by_tenant[tenant_id].add(websocket)
        log.info(
            "🔌 Client connected to WebSocket",
            tenant_id=tenant_id,
            tenant_conns=len(self.by_tenant[tenant_id]),
        )

    def disconnect(self, websocket: WebSocket, tenant_id: str):
        conns = self.by_tenant.get(tenant_id)
        if conns and websocket in conns:
            conns.discard(websocket)
            if not conns:
                del self.by_tenant[tenant_id]
            log.info("🔌 Client disconnected from WebSocket", tenant_id=tenant_id)

    async def broadcast_incident_update(self, incident_data: dict, tenant_id: str):
        """Send an incident update only to sockets owned by ``tenant_id``."""
        conns = self.by_tenant.get(tenant_id)
        if not conns:
            return

        message = json.dumps({"type": "incident_update", "data": incident_data})
        dead = []
        for connection in conns:
            try:
                await connection.send_text(message)
            except Exception:
                dead.append(connection)

        for d in dead:
            self.disconnect(d, tenant_id)


# Singleton manager instance
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Authenticate the handshake: token from the ?token= query param, or the
    # Clerk __session cookie (same-origin fallback). Reject if there is no
    # resolvable tenant — an unauthenticated socket has no tenant to scope to.
    token = websocket.query_params.get("token") or websocket.cookies.get("__session", "")
    tenant_id = _tenant_from_token(token)
    if not tenant_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(websocket, tenant_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, tenant_id)
    except Exception as e:
        log.error("❌ WebSocket error", error=str(e))
        manager.disconnect(websocket, tenant_id)
