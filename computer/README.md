# Computer Module

---

## 中文文档

### 1. 模块职责

`computer` 提供本机控制能力封装，主要面向工具调用场景。

### 2. 关键文件

- `computer/base.py`：控制器基类
- `computer/browser.py`：浏览器控制（Playwright）
- `computer/filesystem.py`：文件系统能力
- `computer/process.py`：进程管理能力
- `computer/screen.py`：屏幕相关能力

### 3. 工作流

1. 上层发起某个控制动作
2. 对应 controller 执行并返回结构化结果
3. 上层根据结果生成最终用户回复

### 4. 注意事项

- 这是高权限模块，务必限制可执行范围
- 浏览器能力依赖 Playwright 浏览器安装
- 错误需显式返回，不要无声失败

---

## English Documentation

### 1. Purpose

`computer` wraps host-side control capabilities for tool execution.

### 2. Key Files

- `computer/base.py`: controller base class
- `computer/browser.py`: browser control (Playwright)
- `computer/filesystem.py`: filesystem operations
- `computer/process.py`: process management
- `computer/screen.py`: screen-related utilities

### 3. Workflow

1. Upper layer triggers an action
2. Matching controller executes and returns structured output
3. Upper layer converts result into final user-visible response

### 4. Notes

- this is high-privilege functionality; scope it carefully
- browser controller requires Playwright browser binaries
- errors should be explicit and observable
