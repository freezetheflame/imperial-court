"""Event broadcaster — SSE fan-out for the frontend.

The bus writes the audit trail (event table); the broadcaster pushes
human-relevant events to connected SSE clients. Decoupled: services call
broadcast() where they'd otherwise just write an event; clients subscribe
via sse(). If nobody's listening, broadcast() is a no-op.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator


class EventBroadcaster:
    def __init__(self, max_queue: int = 100):
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._max_queue = max_queue

    async def broadcast(self, event: str, data: dict[str, Any]) -> None:
        payload = {"event": event, "data": data}
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # slow client — drop oldest to keep the stream alive
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(q)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    # heartbeat so proxies don't kill idle connections
                    yield {"event": "ping", "data": {}}
        finally:
            self._subscribers.discard(q)

    @staticmethod
    def format_sse(payload: dict[str, Any]) -> str:
        return f"event: {payload['event']}\ndata: {json.dumps(payload['data'], ensure_ascii=False)}\n\n"
