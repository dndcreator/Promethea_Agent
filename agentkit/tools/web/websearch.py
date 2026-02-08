"""
Web搜索工具 - 使用DuckDuckGo免费API
无需API密钥，开箱即用
"""

import logging
from typing import Optional, List, Dict, Any
import asyncio

logger = logging.getLogger(__name__)


class WebSearchService:
    """Web搜索服务（DuckDuckGo）"""
    
    def __init__(self):
        self.name = "websearch"
        self.max_results = 5
        logger.info("WebSearchService 初始化完成（DuckDuckGo）")
    
    async def search(self, query: str, max_results: Optional[int] = None) -> str:
        """
        搜索网络内容
        
        Args:
            query: 搜索关键词
            max_results: 最大结果数量（默认5）
        
        Returns:
            格式化的搜索结果字符串
        """
        try:
            if not query or not query.strip():
                return "❌ 搜索关键词不能为空"
            
            limit = max_results if max_results and max_results > 0 else self.max_results
            
            # 使用duckduckgo_search库
            try:
                from duckduckgo_search import DDGS
                
                logger.info(f"正在搜索: {query} (最多{limit}条结果)")
                
                # 执行搜索
                results = []
                with DDGS() as ddgs:
                    for result in ddgs.text(query, max_results=limit):
                        results.append(result)
                
                if not results:
                    return f"🔍 未找到关于 '{query}' 的搜索结果"
                
                # 格式化输出
                formatted_results = [f"🔍 搜索结果：'{query}' (共{len(results)}条)\n"]
                
                for i, result in enumerate(results, 1):
                    title = result.get('title', '无标题')
                    body = result.get('body', '无描述')
                    link = result.get('href', '')
                    
                    formatted_results.append(
                        f"{i}. **{title}**\n"
                        f"   {body}\n"
                        f"   🔗 {link}\n"
                    )
                
                return "\n".join(formatted_results)
                
            except ImportError:
                # 如果库未安装，提示用户
                return (
                    "❌ 缺少依赖库 'duckduckgo-search'\n"
                    "请安装: pip install duckduckgo-search"
                )
                
        except Exception as e:
            error_msg = f"搜索失败: {str(e)}"
            logger.error(error_msg)
            return f"❌ {error_msg}"
    
    async def quick_answer(self, query: str) -> str:
        """
        快速问答（DuckDuckGo Instant Answers）
        
        Args:
            query: 问题
        
        Returns:
            直接答案或搜索结果
        """
        try:
            from duckduckgo_search import DDGS
            
            logger.info(f"正在查询快速答案: {query}")
            
            with DDGS() as ddgs:
                # 尝试获取即时答案
                answers = list(ddgs.answers(query))
                
                if answers:
                    answer = answers[0]
                    text = answer.get('text', '')
                    url = answer.get('url', '')
                    
                    result = f"💡 快速答案：\n{text}"
                    if url:
                        result += f"\n🔗 来源: {url}"
                    return result
                else:
                    # 如果没有即时答案，返回普通搜索
                    return await self.search(query, max_results=3)
                    
        except ImportError:
            return await self.search(query, max_results=3)
        except Exception as e:
            logger.error(f"快速问答失败: {e}")
            # 降级到普通搜索
            return await self.search(query, max_results=3)
    
    async def news_search(self, query: str, max_results: Optional[int] = None) -> str:
        """
        搜索新闻
        
        Args:
            query: 搜索关键词
            max_results: 最大结果数量
        
        Returns:
            格式化的新闻结果
        """
        try:
            from duckduckgo_search import DDGS
            
            limit = max_results if max_results and max_results > 0 else self.max_results
            
            logger.info(f"正在搜索新闻: {query}")
            
            results = []
            with DDGS() as ddgs:
                for result in ddgs.news(query, max_results=limit):
                    results.append(result)
            
            if not results:
                return f"📰 未找到关于 '{query}' 的新闻"
            
            formatted_results = [f"📰 新闻搜索：'{query}' (共{len(results)}条)\n"]
            
            for i, result in enumerate(results, 1):
                title = result.get('title', '无标题')
                body = result.get('body', '无描述')
                url = result.get('url', '')
                date = result.get('date', '')
                source = result.get('source', '')
                
                formatted_results.append(
                    f"{i}. **{title}**\n"
                    f"   {body}\n"
                    f"   📅 {date} | 来源: {source}\n"
                    f"   🔗 {url}\n"
                )
            
            return "\n".join(formatted_results)
            
        except ImportError:
            return "❌ 缺少依赖库，请安装: pip install duckduckgo-search"
        except Exception as e:
            error_msg = f"新闻搜索失败: {str(e)}"
            logger.error(error_msg)
            return f"❌ {error_msg}"
