"""Live push to the browser (Server-Sent Events). One queue per open tab, grouped by user.

`notify()` is safe to call from the threads FastAPI runs normal routes in; it hands the event to the event loop that is
serving the open streams. Nothing is stored: if no tab is open the event is simply dropped (the data is already saved).
"""
import asyncio
import threading
from collections import defaultdict
from typing import Dict, Set

_lock = threading.Lock()
_subs: Dict[int, Set["asyncio.Queue"]] = defaultdict(set)
_loop: "asyncio.AbstractEventLoop | None" = None
MAX_TABS_PER_USER = 8


def subscribe(uid: int) -> "asyncio.Queue":
    global _loop
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    with _lock:
        _loop = asyncio.get_running_loop()
        _subs[uid].add(q)
        if len(_subs[uid]) > MAX_TABS_PER_USER:  # drop the oldest tab's stream
            _subs[uid].discard(next(iter(_subs[uid])))
    return q


def unsubscribe(uid: int, q: "asyncio.Queue"):
    with _lock:
        _subs[uid].discard(q)
        if not _subs[uid]:
            _subs.pop(uid, None)


def listeners(uid: int) -> int:
    with _lock:
        return len(_subs.get(uid, ()))


def notify(uid, event: dict):
    if uid is None:
        return
    with _lock:
        qs, loop = list(_subs.get(uid, ())), _loop
    if not qs or loop is None:
        return

    def _put():
        for q in qs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
    try:
        loop.call_soon_threadsafe(_put)
    except RuntimeError:  # loop already closed (shutdown)
        pass
