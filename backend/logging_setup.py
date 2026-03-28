"""
Samuraizer – Logging setup.
Configures file + console logging and provides an in-memory ring-buffer
for the /logs API endpoint.
"""

import time
import logging
import threading
import collections

from backend.config import LOG_PATH


# ---------------------------------------------------------------------------
# Standard logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
logger = logging.getLogger("samuraizer")
ollama_logger = logging.getLogger("ollama")
ollama_logger.setLevel(logging.DEBUG)


# ---------------------------------------------------------------------------
# In-memory log ring-buffer (exposed via GET /logs)
# ---------------------------------------------------------------------------
class MemoryLogHandler(logging.Handler):
    """Thread-safe ring-buffer that keeps the last 2000 log records."""
    _MAX = 2000

    def __init__(self):
        super().__init__(logging.DEBUG)
        self._lock = threading.Lock()
        self._records = collections.deque(maxlen=self._MAX)
        self._counter = 0

    def emit(self, record: logging.LogRecord):
        with self._lock:
            self._counter += 1
            self._records.append({
                "id":    self._counter,
                "ts":    time.strftime("%H:%M:%S", time.localtime(record.created)),
                "level": record.levelname,
                "name":  record.name,
                "msg":   record.getMessage(),
            })

    def get_since(self, since: int) -> list:
        with self._lock:
            return [r for r in self._records if r["id"] > since]

    def clear(self):
        with self._lock:
            self._records.clear()
            self._counter = 0


memory_log_handler = MemoryLogHandler()
logging.getLogger().addHandler(memory_log_handler)
