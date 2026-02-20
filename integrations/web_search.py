"""
Web search integration.
Provides real-time web and news search for research agents via the Brave Search API.
"""

import os
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class WebSearchClient:
    """Client for web search via Brave Search API."""

    def __init__(self):
        self.api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")

        if not self.api_key:
            logger.warning("Brave Search API key not configured. Web search disabled.")
            self.enabled = False
            return

        self.enabled = True
        self.base_url = "https://api.search.brave.com/res/v1"
        self.headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key,
        }
        logger.info("Web search client initialized (Brave Search)")

    def search(self, query: str, count: int = 5) -> Optional[list[dict]]:
        """
        Search the web. Returns a list of results with title, url, and snippet.
        """
        if not self.enabled:
            return None

        try:
            resp = requests.get(
                f"{self.base_url}/web/search",
                headers=self.headers,
                params={"q": query, "count": min(count, 10)},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for item in data.get("web", {}).get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", ""),
                })
            return results

        except Exception as e:
            logger.error(f"Web search failed for '{query}': {e}")
            return None

    def news_search(self, query: str, count: int = 5) -> Optional[list[dict]]:
        """
        Search for recent news. Returns a list of news results with title, url, snippet, and age.
        """
        if not self.enabled:
            return None

        try:
            resp = requests.get(
                f"{self.base_url}/news/search",
                headers=self.headers,
                params={"q": query, "count": min(count, 10)},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for item in data.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", ""),
                    "age": item.get("age", ""),
                    "source": item.get("meta_url", {}).get("hostname", ""),
                })
            return results

        except Exception as e:
            logger.error(f"News search failed for '{query}': {e}")
            return None
