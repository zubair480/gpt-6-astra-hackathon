"""Bounded replay guard keyed on (session_id, request_id). Stores keys only, never bodies."""

from __future__ import annotations

import threading
from collections import OrderedDict


class ReplayGuard:
    def __init__(self, capacity: int = 10_000) -> None:
        self._seen: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._capacity = capacity
        self._lock = threading.Lock()

    def register(self, session_id: str, request_id: str) -> bool:
        """Return True the first time a key is seen, False on any repeat."""
        key = (session_id, request_id)
        with self._lock:
            if key in self._seen:
                return False
            self._seen[key] = None
            while len(self._seen) > self._capacity:
                self._seen.popitem(last=False)
            return True
