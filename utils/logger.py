"""
"""
import logging
import sys
import threading
import time
from pathlib import Path
from loguru import logger


class RepeatedAccessFilter(logging.Filter):
    """Bound identical access rows without hiding their first occurrence."""

    def __init__(self, interval_s: float = 5.0) -> None:
        super().__init__()
        self.interval_s = interval_s
        self._last_seen: dict[tuple[object, ...], float] = {}
        self._lock = threading.Lock()

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args if isinstance(record.args, tuple) else ()
        key = (args[1], args[2], args[4]) if len(args) >= 5 else (record.getMessage(),)
        now = time.monotonic()
        with self._lock:
            previous = self._last_seen.get(key)
            self._last_seen[key] = now
        return previous is None or now - previous >= self.interval_s


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

def setup_logger(
    log_dir: str = "logs",
    level: str | None = None,
    *,
    include_model_payloads: bool = False,
):
    """Configure concise console output and a separate diagnostic file."""
    logger.remove()
    resolved_level = str(level or "INFO").strip().upper()
    if resolved_level not in {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}:
        resolved_level = "INFO"

    # Ensure Windows console/file output keeps UTF-8 Chinese text readable.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    
    console_level = "INFO" if resolved_level in {"TRACE", "DEBUG"} else resolved_level
    logger.add(
        sys.stderr,
        level=console_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    
    logger.add(
        f"{log_dir}/app.log",
        rotation="00:00",
        retention="10 days",
        compression="zip",
        enqueue=True,
        level=resolved_level,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} | {extra} | {message}",
        encoding="utf-8",
    )
    
    logger.add(
        f"{log_dir}/error.log",
        rotation="10 MB",
        retention="30 days",
        level="ERROR",
        backtrace=True,        # Include detailed stack traces
        diagnose=False,        # Avoid logging local variables such as passwords.
        encoding="utf-8",
    )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # Model payloads contain prompts, conversations, and recalled memory. Keep
    # dependency wire logs opt-in even when Promethea's own log level is DEBUG.
    dependency_level = logging.DEBUG if include_model_payloads else logging.WARNING
    for logger_name in ("openai", "httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(dependency_level)
    
    for logger_name in ("uvicorn", "uvicorn.error", "fastapi"):
        mod_logger = logging.getLogger(logger_name)
        mod_logger.handlers = [InterceptHandler()]
        mod_logger.propagate = False

    access_handler = InterceptHandler()
    access_handler.addFilter(RepeatedAccessFilter())
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers = [access_handler]
    access_logger.propagate = False

    logger.info(
        "Logger initialized (console={}, file={}, model_payloads={})",
        console_level,
        resolved_level,
        dependency_level == logging.DEBUG,
    )

    return logger
