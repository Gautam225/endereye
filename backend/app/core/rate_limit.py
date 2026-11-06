"""In-memory sliding-window limiter, used to slow down password guessing.

Kept in the process: fine for one backend process. With several workers, each keeps its
own count (Step 13 revisits this for deployment).
"""

import time
from collections import deque
from collections.abc import Callable

MAX_TRACKED_KEYS = 10_000


class SlidingWindowLimiter:
    def __init__(
        self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def retry_after(self, key: str) -> float:
        """Seconds until `key` may try again; 0 when it may try now."""
        hits = self._prune(key)
        if len(hits) < self.limit:
            return 0.0
        return max(0.0, self.window - (self._clock() - hits[0]))

    def hit(self, key: str) -> None:
        self._prune(key).append(self._clock())
        if len(self._hits) > MAX_TRACKED_KEYS:
            for stale in [k for k, v in self._hits.items() if not v]:
                del self._hits[stale]

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def _prune(self, key: str) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        cutoff = self._clock() - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits
