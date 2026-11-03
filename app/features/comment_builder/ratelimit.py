"""
A simple limit so a stuck button can't run up the OpenAI bill: 30 AI requests
a minute per user, and per IP. In memory, per process: it resets on a restart.
"""
import threading
import time

from app.core.views import ViewError

LIMIT = 30
WINDOW_SECONDS = 60

hits = {}
hits_lock = threading.Lock()


def rate_limit(key, message="Too many AI requests. Please wait a minute."):
    now = time.time()
    with hits_lock:
        recent = [t for t in hits.get(key, []) if now - t < WINDOW_SECONDS]
        if len(recent) >= LIMIT:
            raise ViewError(429, message)
        recent.append(now)
        hits[key] = recent
