"""
统一日志系统 (Based on Moltbot's Observability Philosophy)
使用 Loguru 替代标准 logging，提供结构化、分层级、自动轮转的日志能力。
"""
import sys
import logging
import inspect
from pathlib import Path
from loguru import logger

# 拦截标准库 logging 的处理器
class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        # 获取对应的 Loguru level
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 查找调用者的帧，确保日志显示正确的文件名和行号
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

def setup_logger(log_dir: str = "logs", level: str = "INFO"):
    """
    配置全局 Logger
    :param log_dir: 日志存储目录
    :param level: 控制台日志级别
    """
    # 1. 移除默认 handler
    logger.remove()
    
    # 2. 确保日志目录存在
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    
    # 3. 配置控制台输出 (高亮, 简洁)
    # 格式参考: [时间] [级别] [模块:行号] - 内容
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    
    # 4. 配置全量日志文件 (详细, 自动轮转)
    logger.add(
        f"{log_dir}/app.log",
        rotation="00:00",      # 每天午夜轮转
        retention="10 days",   # 保留10天
        compression="zip",     # 压缩旧日志
        enqueue=True,          # 异步写入
        level="DEBUG",         # 记录所有细节
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} | {extra} | {message}"
    )
    
    # 5. 配置错误日志文件 (仅错误)
    logger.add(
        f"{log_dir}/error.log",
        rotation="10 MB",      # 按大小轮转
        retention="30 days",
        level="ERROR",
        backtrace=True,        # 记录详细堆栈
        diagnose=True          # 诊断模式
    )

    # 6. 拦截 Uvicorn 和 FastAPI 的日志
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    
    # 禁用 Uvicorn 自己的 handlers，改用我们的拦截器
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
        mod_logger = logging.getLogger(logger_name)
        mod_logger.handlers = [InterceptHandler()]
        mod_logger.propagate = False

    logger.info("✅ 日志系统初始化完成 (Loguru)")

    return logger
