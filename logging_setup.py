"""Central logging configuration.

Configures a rotating file handler (so the log survives on the mounted
Azure file share across container restarts) plus a stdout handler, and
quiets noisy third-party loggers. Idempotent: safe to call multiple times
(e.g. bot.py and dashboard/app.py both importing it) without double-
attaching handlers.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_configured = False


def configure_logging(level: int = logging.INFO, log_dir: str | None = None) -> str:
    """Idempotent. Returns the absolute path of the log file."""
    global _configured

    if log_dir is None:
        log_dir = "."
    log_dir = log_dir or "."
    log_path = os.path.abspath(os.path.join(log_dir, "bot.log"))

    if _configured:
        return log_path

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    file_handler = RotatingFileHandler(
        log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    # Quiet noisy third-party loggers.
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    _configured = True
    return log_path
