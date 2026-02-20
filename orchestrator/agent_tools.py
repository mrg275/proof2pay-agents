"""
Agent-specific tools. Defines and handles tools for specialist agents.
Currently: GitHub tools for Technical PM, web search tools for research agents.
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─── GitHub Tools for Technical PM ───

GITHUB_LIST_FILES_TOOL = {
    "name": "github_list_files",
    "description": (
        "List files and directories in the GitHub repository at a given path. "
        "Use this to explore the codebase structure. Start with '' for the repo root, "
        "then drill into specific directories."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to list. Use '' for repo root. E.g., 'src/api', 'tests'.",
            },
            "branch": {
                "type": "string",
                "description": "Branch name. Defaults to 'main'.",
            },
        },
        "required": [],
    },
}

GITHUB_READ_FILE_TOOL = {
    "name": "github_read_file",
    "description": (
        "Read the contents of a specific file from the GitHub repository. "
        "Use this to examine source code, configuration files, tests, etc."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Full file path in the repo. E.g., 'src/api/routes.py'.",
            },
            "branch": {
                "type": "string",
                "description": "Branch name. Defaults to 'main'.",
            },
        },
        "required": ["path"],
    },
}

GITHUB_RECENT_COMMITS_TOOL = {
    "name": "github_recent_commits",
    "description": (
        "Get the most recent commits from the repository. Shows commit messages, "
        "authors, and dates. Use this to understand what's been recently changed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "Number of recent commits to retrieve (max 20). Defaults to 10.",
            },
            "branch": {
                "type": "string",
                "description": "Branch name. Defaults to 'main'.",
            },
        },
        "required": [],
    },
}

GITHUB_COMMIT_DIFF_TOOL = {
    "name": "github_commit_diff",
    "description": (
        "Get the diff (code changes) for a specific commit. Use this after "
        "seeing recent commits to understand what exactly changed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sha": {
                "type": "string",
                "description": "Commit SHA (short or full).",
            },
        },
        "required": ["sha"],
    },
}

GITHUB_OPEN_PRS_TOOL = {
    "name": "github_open_prs",
    "description": "List currently open pull requests with their titles, authors, and labels.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

TECHNICAL_PM_TOOLS = [
    GITHUB_LIST_FILES_TOOL,
    GITHUB_READ_FILE_TOOL,
    GITHUB_RECENT_COMMITS_TOOL,
    GITHUB_COMMIT_DIFF_TOOL,
    GITHUB_OPEN_PRS_TOOL,
]

# ─── Web Search Tools for Research Agents ───

WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "Search the web for current information. Returns titles, URLs, and snippets "
        "from search results. Use this to find recent news, company information, "
        "government announcements, or any real-time data."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query. Be specific for better results.",
            },
            "count": {
                "type": "integer",
                "description": "Number of results to return (max 10). Defaults to 5.",
            },
        },
        "required": ["query"],
    },
}

WEB_NEWS_SEARCH_TOOL = {
    "name": "web_news_search",
    "description": (
        "Search for recent news articles. Returns titles, URLs, and snippets "
        "from news sources. Use this for monitoring competitor announcements, "
        "industry developments, and government news."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "News search query.",
            },
            "count": {
                "type": "integer",
                "description": "Number of results to return (max 10). Defaults to 5.",
            },
        },
        "required": ["query"],
    },
}

RESEARCH_AGENT_TOOLS = [WEB_SEARCH_TOOL, WEB_NEWS_SEARCH_TOOL]


class AgentToolHandler:
    """Handles tool calls for specialist agents (non-dispatch tools)."""

    def __init__(self, github_client=None, web_search_client=None):
        self.github = github_client
        self.web_search = web_search_client

    def handle_tool_call(self, tool_call: dict) -> dict:
        """Execute a tool call and return the result."""
        name = tool_call["name"]
        inputs = tool_call.get("input", {})
        tool_id = tool_call["id"]

        handler_map = {
            # GitHub tools
            "github_list_files": self._handle_github_list_files,
            "github_read_file": self._handle_github_read_file,
            "github_recent_commits": self._handle_github_recent_commits,
            "github_commit_diff": self._handle_github_commit_diff,
            "github_open_prs": self._handle_github_open_prs,
            # Web search tools
            "web_search": self._handle_web_search,
            "web_news_search": self._handle_web_news_search,
        }

        handler = handler_map.get(name)
        if not handler:
            return {
                "tool_use_id": tool_id,
                "result": f"Unknown tool: {name}",
                "success": False,
            }

        try:
            result = handler(inputs)
            return {"tool_use_id": tool_id, "result": result, "success": True}
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            return {"tool_use_id": tool_id, "result": f"Tool error: {e}", "success": False}

    # ─── GitHub Tool Handlers ───

    def _handle_github_list_files(self, inputs: dict) -> str:
        if not self.github or not self.github.enabled:
            return "GitHub integration not configured."
        path = inputs.get("path", "")
        branch = inputs.get("branch", "main")
        files = self.github.get_file_tree(path, branch)
        if files is None:
            return f"Could not list files at '{path}'"
        return json.dumps(files, indent=2)

    def _handle_github_read_file(self, inputs: dict) -> str:
        if not self.github or not self.github.enabled:
            return "GitHub integration not configured."
        path = inputs["path"]
        branch = inputs.get("branch", "main")
        content = self.github.get_file_content(path, branch)
        if content is None:
            return f"Could not read file '{path}'"
        return content

    def _handle_github_recent_commits(self, inputs: dict) -> str:
        if not self.github or not self.github.enabled:
            return "GitHub integration not configured."
        count = min(inputs.get("count", 10), 20)
        branch = inputs.get("branch", "main")
        commits = self.github.get_recent_commits(count, branch)
        if commits is None:
            return "Could not retrieve commits."
        return json.dumps(commits, indent=2)

    def _handle_github_commit_diff(self, inputs: dict) -> str:
        if not self.github or not self.github.enabled:
            return "GitHub integration not configured."
        sha = inputs["sha"]
        diff = self.github.get_commit_diff(sha)
        return diff or f"Could not get diff for commit {sha}"

    def _handle_github_open_prs(self, inputs: dict) -> str:
        if not self.github or not self.github.enabled:
            return "GitHub integration not configured."
        prs = self.github.get_open_prs()
        if prs is None:
            return "Could not retrieve pull requests."
        return json.dumps(prs, indent=2)

    # ─── Web Search Tool Handlers ───

    def _handle_web_search(self, inputs: dict) -> str:
        if not self.web_search or not self.web_search.enabled:
            return "Web search not configured."
        query = inputs["query"]
        count = min(inputs.get("count", 5), 10)
        results = self.web_search.search(query, count)
        if results is None:
            return f"Search failed for '{query}'"
        return json.dumps(results, indent=2)

    def _handle_web_news_search(self, inputs: dict) -> str:
        if not self.web_search or not self.web_search.enabled:
            return "Web search not configured."
        query = inputs["query"]
        count = min(inputs.get("count", 5), 10)
        results = self.web_search.news_search(query, count)
        if results is None:
            return f"News search failed for '{query}'"
        return json.dumps(results, indent=2)
