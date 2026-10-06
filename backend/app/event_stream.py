"""In-process pub/sub with durable JSONL persistence (stand-in for Redpanda/Kafka).
Only anonymised signals are published: no merchant, no exact amount, no raw text."""
import json
import threading
from collections import deque
from datetime import datetime
from typing import Callable, List

from .database import DATA_DIR, utcnow

LOG_PATH = DATA_DIR / "events.jsonl"
_lock = threading.Lock()
_buffer = deque(maxlen=500)
_subscribers: List[Callable[[dict], None]] = []
_seq = 0


def _load():
    global _seq
    if LOG_PATH.exists():
        for line in LOG_PATH.read_text(encoding="utf-8").splitlines()[-500:]:
            try:
                ev = json.loads(line)
                _buffer.append(ev)
                _seq = max(_seq, ev.get("offset", 0))
            except json.JSONDecodeError:
                continue


_load()


def subscribe(fn: Callable[[dict], None]):
    _subscribers.append(fn)


def publish(topic: str, payload: dict, uid=None) -> dict:
    """`uid` tags the event with its owner so /events/recent only shows a person their own signals."""
    global _seq
    with _lock:
        _seq += 1
        ev = {"offset": _seq, "topic": topic, "ts": utcnow().isoformat(timespec="seconds") + "Z", **payload}
        if uid is not None:
            ev["uid"] = uid
        _buffer.append(ev)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev) + "\n")
    for fn in list(_subscribers):
        try:
            fn(ev)
        except Exception:
            pass
    return ev


def recent(n: int = 50, uid=None) -> list:
    """Newest first. With `uid`, only that user's events (and none of anyone else's)."""
    rows = [e for e in _buffer if uid is None or e.get("uid") == uid]
    return [{k: v for k, v in e.items() if k != "uid"} for e in rows[-n:][::-1]]


def purge(uid) -> int:
    """Forget one user's events (memory and the on-disk log). Used when an account is deleted."""
    global _buffer
    with _lock:
        before = len(_buffer)
        keep = [e for e in _buffer if e.get("uid") != uid]
        _buffer = deque(keep, maxlen=500)
        if LOG_PATH.exists():
            lines = []
            for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
                try:
                    if json.loads(line).get("uid") == uid:
                        continue
                except json.JSONDecodeError:
                    continue
                lines.append(line)
            LOG_PATH.write_text(chr(10).join(lines) + (chr(10) if lines else ""), encoding="utf-8")
        return before - len(_buffer)


def reset():
    """Empty everything (tests)."""
    with _lock:
        _buffer.clear()
        if LOG_PATH.exists():
            LOG_PATH.unlink()
