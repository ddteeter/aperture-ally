"""In-process event bus fanned out to WebSocket clients.

Events are notifications only; the database is authoritative. On reconnect clients re-fetch state.
"""

from __future__ import annotations

import asyncio
import itertools
from collections import deque
from typing import Any

from .domain.models import utcnow


class EventBus:
    def __init__(self, history: int = 500):
        self._seq = itertools.count(1)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.recent: deque[dict[str, Any]] = deque(maxlen=history)

    def publish(self, type_: str, *, session_id: str | None = None, capture_id: str | None = None,
                **payload: Any) -> dict[str, Any]:
        event = {
            "seq": next(self._seq),
            "type": type_,
            "ts": utcnow(),
            "session_id": session_id,
            "capture_id": capture_id,
            "payload": payload,
        }
        self.recent.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow client: drop it; it will reconnect and re-fetch authoritative state.
                self._subscribers.discard(q)
        return event

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)

    def wait_for(self, predicate, timeout: float = 5.0):
        """Test helper: await the first future event matching ``predicate``."""
        q = self.subscribe()

        async def _wait():
            try:
                while True:
                    ev = await q.get()
                    if predicate(ev):
                        return ev
            finally:
                self.unsubscribe(q)

        return asyncio.wait_for(_wait(), timeout)
