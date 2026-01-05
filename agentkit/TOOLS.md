# MCP 工具列表

## websearch - 网络搜索

**位置**: `agentkit/tools/websearch.py`  
**依赖**: `duckduckgo-search>=4.0.0`  
**API Key**: 无需

### 方法

| 方法 | 说明 | 调用示例 |
|------|------|----------|
| `search` | 网络搜索 | `{"tool_name": "search", "service_name": "websearch", "query": "AI"}` |
| `quick_answer` | 快速问答 | `{"tool_name": "quick_answer", "service_name": "websearch", "query": "什么是AI"}` |
| `news_search` | 新闻搜索 | `{"tool_name": "news_search", "service_name": "websearch", "query": "科技"}` |

---

## 添加新工具

1. 在 `agentkit/tools/` 创建 `your_tool.py`
2. 创建 `agent-manifest.json` 配置文件
3. 在本文件添加一条记录
4. 重启服务自动加载

