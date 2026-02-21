"""Web search tools powered by DuckDuckGo."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class WebSearchService:
    """Simple DuckDuckGo search wrapper."""

    def __init__(self):
        self.name = "websearch"
        self.max_results = 5
        logger.info("WebSearchService initialized")

    async def search(self, query: str, max_results: Optional[int] = None) -> str:
        """Run a general web search."""
        try:
            if not query or not query.strip():
                return "Error: query cannot be empty"

            limit = max_results if max_results and max_results > 0 else self.max_results

            try:
                from duckduckgo_search import DDGS

                logger.info("Search: %s (max=%s)", query, limit)
                results = []
                with DDGS() as ddgs:
                    for result in ddgs.text(query, max_results=limit):
                        results.append(result)

                if not results:
                    return f"No results found for '{query}'"

                formatted = [f"Search results for '{query}' ({len(results)}):\n"]
                for i, result in enumerate(results, 1):
                    title = result.get("title", "Untitled")
                    body = result.get("body", "")
                    link = result.get("href", "")
                    formatted.append(
                        f"{i}. **{title}**\n"
                        f"   {body}\n"
                        f"   {link}\n"
                    )
                return "\n".join(formatted)
            except ImportError:
                return "Missing dependency: install duckduckgo-search"
        except Exception as e:
            logger.error("Search failed: %s", e)
            return f"Error: search failed: {e}"

    async def quick_answer(self, query: str) -> str:
        """Try instant answer first, fallback to normal search."""
        try:
            from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                answers = list(ddgs.answers(query))
                if answers:
                    answer = answers[0]
                    text = answer.get("text", "")
                    url = answer.get("url", "")
                    result = f"Quick answer:\n{text}"
                    if url:
                        result += f"\nSource: {url}"
                    return result
            return await self.search(query, max_results=3)
        except ImportError:
            return await self.search(query, max_results=3)
        except Exception as e:
            logger.error("Quick answer failed: %s", e)
            return await self.search(query, max_results=3)

    async def news_search(self, query: str, max_results: Optional[int] = None) -> str:
        """Search news results."""
        try:
            from duckduckgo_search import DDGS

            limit = max_results if max_results and max_results > 0 else self.max_results
            results = []
            with DDGS() as ddgs:
                for result in ddgs.news(query, max_results=limit):
                    results.append(result)

            if not results:
                return f"No news found for '{query}'"

            formatted = [f"News results for '{query}' ({len(results)}):\n"]
            for i, result in enumerate(results, 1):
                title = result.get("title", "Untitled")
                body = result.get("body", "")
                url = result.get("url", "")
                date = result.get("date", "")
                source = result.get("source", "")
                formatted.append(
                    f"{i}. **{title}**\n"
                    f"   {body}\n"
                    f"   {date} | {source}\n"
                    f"   {url}\n"
                )
            return "\n".join(formatted)
        except ImportError:
            return "Missing dependency: install duckduckgo-search"
        except Exception as e:
            logger.error("News search failed: %s", e)
            return f"Error: news search failed: {e}"
