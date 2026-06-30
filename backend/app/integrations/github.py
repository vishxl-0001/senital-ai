"""
Sentinel AI — GitHub Integration
Fetches recent commits and deployments to determine if a bad code push caused an incident.
"""

import httpx
import structlog
from app.config import settings

log = structlog.get_logger()

# Constants
GITHUB_API = "https://api.github.com"

async def get_recent_commits(repo: str, branch: str = "main", limit: int = 5) -> list:
    """
    Fetch recent commits from a GitHub repository.
    Needs GITHUB_PAT configured in environment.
    """
    if not settings.GITHUB_PAT:
        log.warning("GITHUB_PAT not set, skipping commit fetch")
        return []

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {settings.GITHUB_PAT}",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo}/commits",
                headers=headers,
                params={"sha": branch, "per_page": limit}
            )
            resp.raise_for_status()
            data = resp.json()
            
            commits = []
            for item in data:
                commits.append({
                    "sha": item["sha"][:7],
                    "message": item["commit"]["message"].split("\n")[0],
                    "author": item["commit"]["author"]["name"],
                    "date": item["commit"]["author"]["date"],
                    "url": item["html_url"]
                })
            return commits
    except Exception as e:
        log.error("Failed to fetch GitHub commits", error=str(e), repo=repo)
        return []
