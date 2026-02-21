"""
"""
import sys
import logging
import inspect
from pathlib import Path
from loguru import logger

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

def setup_logger(log_dir: str = "logs", level: str = "INFO"):
    """
    """
    logger.remove()
    
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    
    logger.add(
        f"{log_dir}/app.log",
        rotation="00:00",
        retention="10 days",
        compression="zip",
        enqueue=True,
        level="DEBUG",         # Log all details
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} | {extra} | {message}"
    )
    
    logger.add(
        f"{log_dir}/error.log",
        rotation="10 MB",
        retention="30 days",
        level="ERROR",
        backtrace=True,        # Include detailed stack traces
        diagnose=True          # Enable diagnose mode
    )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
        mod_logger = logging.getLogger(logger_name)
        mod_logger.handlers = [InterceptHandler()]
        mod_logger.propagate = False

    logger.info("Logger initialized")

    return logger
