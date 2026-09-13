"""WebSocket connection manager (fan-out broadcast to every dashboard)."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger("energy.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[WebSocket] = set()

    @property
    def count(self) -> int:
        return len(self.active)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.add(websocket)
        log.info("ws client connected (%d total)", self.count)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active.discard(websocket)
        log.info("ws client disconnected (%d total)", self.count)

    async def send(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        await websocket.send_text(json.dumps(message, separators=(",", ":")))

    async def broadcast(self, message: dict[str, Any]) -> None:
        if not self.active:
            return
        payload = json.dumps(message, separators=(",", ":"))
        stale: list[WebSocket] = []
        for websocket in list(self.active):
            try:
                await websocket.send_text(payload)
            except (WebSocketDisconnect, RuntimeError):
                stale.append(websocket)
            except Exception:  # pragma: no cover - defensive
                log.exception("broadcast failed")
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)


manager = ConnectionManager()
