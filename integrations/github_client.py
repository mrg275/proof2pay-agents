"""
GitHub integration.
Provides repository access for the Technical PM agent to query live codebase state.
"""

import os
import base64
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class GitHubClient:
    """Client for reading repository data from GitHub."""

    def __init__(self):
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.repo = os.environ.get("GITHUB_REPO", "")

        if not self.token or not self.repo:
            logger.warning("GitHub credentials not configured. GitHub integration disabled.")
            self.enabled = False
            return

        self.enabled = True
        self.base_url = f"https://api.github.com/repos/{self.repo}"
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
        }
        logger.info(f"GitHub client initialized for {self.repo}")

    def _get(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict | list]:
        """Make a GET request to the GitHub API."""
        if not self.enabled:
            return None
        try:
            resp = requests.get(
                f"{self.base_url}/{endpoint}",
                headers=self.headers,
                params=params or {},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"GitHub API error ({endpoint}): {e}")
            return None

    def get_file_tree(self, path: str = "", branch: str = "main") -> Optional[list[dict]]:
        """List files and directories at a given path."""
        data = self._get(f"contents/{path}", {"ref": branch})
        if data and isinstance(data, list):
            return [
                {
                    "name": f["name"],
                    "type": f["type"],
                    "path": f["path"],
                    "size": f.get("size", 0),
                }
                for f in data
            ]
        return None

    def get_file_content(self, path: str, branch: str = "main") -> Optional[str]:
        """Read a file's content from the repo."""
        data = self._get(f"contents/{path}", {"ref": branch})
        if data and isinstance(data, dict) and data.get("encoding") == "base64":
            content = base64.b64decode(data["content"]).decode("utf-8")
            # Truncate very large files to prevent context blowout
            if len(content) > 15000:
                return content[:15000] + f"\n\n[TRUNCATED - file is {len(content)} chars total]"
            return content
        return None

    def get_recent_commits(self, n: int = 10, branch: str = "main") -> Optional[list[dict]]:
        """Get the N most recent commits."""
        data = self._get("commits", {"sha": branch, "per_page": min(n, 30)})
        if data and isinstance(data, list):
            return [
                {
                    "sha": c["sha"][:8],
                    "message": c["commit"]["message"],
                    "author": c["commit"]["author"]["name"],
                    "date": c["commit"]["author"]["date"],
                }
                for c in data
            ]
        return None

    def get_commit_diff(self, sha: str) -> Optional[str]:
        """Get the diff for a specific commit."""
        if not self.enabled:
            return None
        try:
            resp = requests.get(
                f"{self.base_url}/commits/{sha}",
                headers={**self.headers, "Accept": "application/vnd.github.v3.diff"},
                timeout=15,
            )
            resp.raise_for_status()
            diff = resp.text
            if len(diff) > 10000:
                return diff[:10000] + f"\n\n[TRUNCATED - diff is {len(diff)} chars total]"
            return diff
        except Exception as e:
            logger.error(f"GitHub API error (diff {sha}): {e}")
            return None

    def get_open_prs(self) -> Optional[list[dict]]:
        """Get open pull requests."""
        data = self._get("pulls", {"state": "open", "per_page": 10})
        if data and isinstance(data, list):
            return [
                {
                    "number": pr["number"],
                    "title": pr["title"],
                    "author": pr["user"]["login"],
                    "created_at": pr["created_at"],
                    "labels": [label["name"] for label in pr.get("labels", [])],
                }
                for pr in data
            ]
        return None

    def get_branch_list(self) -> Optional[list[str]]:
        """Get list of branches."""
        data = self._get("branches", {"per_page": 20})
        if data and isinstance(data, list):
            return [b["name"] for b in data]
        return None
