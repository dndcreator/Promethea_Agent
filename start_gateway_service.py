"""
Startup Script for Gateway Integrated API Server
"""
import sys
import os
import uvicorn
import webbrowser
from utils.logger import setup_logger

if __name__ == "__main__":
    # 初始化日志系统
    logger = setup_logger()
    
    logger.info("=" * 60)
    logger.info("普罗米娅AI助手 - 网关集成版")
    logger.info("=" * 60)
    logger.info("API Service: http://127.0.0.1:8000")
    logger.info("Web UI     : http://127.0.0.1:8000/UI/index.html")
    
    # 自动打开浏览器
    try:
        webbrowser.open("http://127.0.0.1:8000/UI/index.html")
        logger.info("✅ 已自动打开浏览器")
    except Exception as e:
        logger.warning(f"无法自动打开浏览器: {e}")
    
    # Check if we are running in a valid environment
    try:
        import api_server.server
    except Exception as e:
        logger.error(f"无法导入 api_server: {e}")
        import traceback
        logger.error(traceback.format_exc())
        logger.error("请确保已安装项目依赖：pip install -e .")
        sys.exit(1)

    uvicorn.run(
        "api_server.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )
