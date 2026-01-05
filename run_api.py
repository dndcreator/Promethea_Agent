#!/usr/bin/env python3
"""启动FastAPI后端服务器"""
import uvicorn
import time
import webbrowser
import threading

def open_browser():
    time.sleep(2)
    webbrowser.open("http://127.0.0.1:8000/UI")

if __name__ == "__main__":
    print("🚀 启动普罗米娅AI助手 API服务器...")
    print("📍 地址: http://127.0.0.1:8000")
    print("📚 API文档: http://127.0.0.1:8000/docs")
    print("=" * 50)
    
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()

    uvicorn.run(
        "api_server.server:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info"
    )
