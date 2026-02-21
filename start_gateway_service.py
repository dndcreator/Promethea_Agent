"""Startup script for gateway-first service."""

import sys
import webbrowser

import uvicorn

from utils.logger import setup_logger


if __name__ == "__main__":
    logger = setup_logger()

    logger.info("=" * 60)
    logger.info("Promethea - Gateway Service")
    logger.info("=" * 60)
    logger.info("Gateway API : http://127.0.0.1:8000")
    logger.info("Web UI      : http://127.0.0.1:8000/UI/index.html")

    try:
        webbrowser.open("http://127.0.0.1:8000/UI/index.html")
        logger.info("Browser opened")
    except Exception as e:
        logger.warning(f"Failed to open browser automatically: {e}")

    try:
        import gateway.app  # noqa: F401
    except Exception as e:
        logger.error(f"Cannot import gateway app: {e}")
        import traceback

        logger.error(traceback.format_exc())
        logger.error("Please install dependencies first: pip install -e .")
        sys.exit(1)

    uvicorn.run(
        "gateway.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
