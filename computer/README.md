# Computer 模块

Computer 模块提供电脑控制能力，包括浏览器、屏幕、文件系统、进程管理等。

## 架构设计

```
┌─────────────────────────────────────┐
│   ComputerController (统一接口)      │
└─────────────────────────────────────┘
              │
    ┌─────────┼─────────┬─────────┐
    ▼         ▼         ▼         ▼
Browser   Screen   FileSystem  Process
Controller Controller Controller Controller
```

## 核心组件

### 1. ComputerController (`base.py`)

- **职责**: 所有控制器的基类
- **接口**:
  - `execute_action()` - 执行操作
  - `get_status()` - 获取状态
  - `get_capabilities()` - 获取能力列表

### 2. BrowserController (`browser.py`)

- **职责**: 浏览器控制
- **功能**:
  - 打开/关闭浏览器
  - 导航到 URL
  - 点击、输入、滚动
  - 截图
  - 执行 JavaScript

### 3. ScreenController (`screen.py`)

- **职责**: 屏幕控制
- **功能**:
  - 截图
  - 屏幕录制
  - 分辨率获取

### 4. FileSystemController (`filesystem.py`)

- **职责**: 文件系统操作
- **功能**:
  - 文件读写
  - 目录操作
  - 文件搜索
  - 权限管理

### 5. ProcessController (`process.py`)

- **职责**: 进程管理
- **功能**:
  - 启动/停止进程
  - 进程列表
  - 进程监控

## 使用示例

### 浏览器控制

```python
from computer import BrowserController

browser = BrowserController()

# 打开浏览器并导航
browser.navigate("https://example.com")

# 点击元素
browser.click(selector="#button")

# 输入文本
browser.type(selector="#input", text="Hello")

# 截图
browser.screenshot("screenshot.png")
```

### 文件系统操作

```python
from computer import FileSystemController

fs = FileSystemController()

# 读取文件
content = fs.read_file("path/to/file.txt")

# 写入文件
fs.write_file("path/to/file.txt", "content")

# 列出目录
files = fs.list_directory("path/to/dir")
```

### 进程管理

```python
from computer import ProcessController

process = ProcessController()

# 启动进程
process.start("notepad.exe")

# 列出进程
processes = process.list_processes()

# 停止进程
process.stop(pid=1234)
```

## 安全考虑

1. **权限控制**: 某些操作需要管理员权限
2. **沙箱隔离**: 建议在沙箱环境中运行
3. **操作审计**: 记录所有操作日志
4. **资源限制**: 限制 CPU、内存使用

## 配置

电脑控制配置在 `config/default.json` 中：

```json
{
  "computer": {
    "enabled": true,
    "browser": {
      "headless": false,
      "timeout": 30
    },
    "filesystem": {
      "allowed_paths": ["/safe/path"],
      "blocked_paths": ["/system"]
    }
  }
}
```

## 相关文档

- [主 README](../README.md)
- [Gateway 模块](../gateway/README.md)
