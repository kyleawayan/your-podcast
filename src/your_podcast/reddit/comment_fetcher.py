"""Fetch Reddit comments via JSON API (no auth required)."""

import time
from typing import Callable

import requests

from your_podcast.settings import get_settings


def _countdown_sleep(
    seconds: float,
    on_tick: Callable[[int], None] | None = None,
) -> None:
    """Sleep with countdown, calling on_tick each second with remaining time."""
    remaining = int(seconds)
    while remaining > 0:
        if on_tick:
            on_tick(remaining)
        time.sleep(1)
        remaining -= 1


def fetch_comments(
    reddit_url: str,
    limit: int = 10,
    max_retries: int = 3,
    on_wait: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Fetch top comments from a Reddit post via JSON API.

    Args:
        reddit_url: Full Reddit post URL
        limit: Max number of comments to fetch
        max_retries: Max retries on 429 errors
        on_wait: Optional callback(remaining_seconds, attempt) called each second during wait

    Returns:
        List of comment dicts with author, body, score
    """
    settings = get_settings()

    # Add .json to the URL
    json_url = reddit_url.rstrip("/") + ".json"
    if "?" in json_url:
        json_url += f"&limit={limit}"
    else:
        json_url += f"?limit={limit}"

    backoff = 1
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(
                json_url,
                headers={"User-Agent": settings.user_agent},
                timeout=10,
            )

            if resp.status_code == 429:
                if attempt < max_retries:
                    reset_seconds = float(resp.headers.get("X-Ratelimit-Reset", backoff))
                    wait_time = max(reset_seconds, backoff)

                    # Countdown sleep with progress updates
                    def on_tick(remaining: int) -> None:
                        if on_wait:
                            on_wait(remaining, attempt + 1)

                    _countdown_sleep(wait_time, on_tick)
                    backoff *= 2
                    continue
                else:
                    return []  # Give up silently for comments

            resp.raise_for_status()
            data = resp.json()

            # Reddit returns [post_listing, comments_listing]
            if len(data) < 2:
                return []

            comments = []
            for child in data[1]["data"]["children"]:
                if child["kind"] != "t1":  # t1 = comment
                    continue

                comment_data = child["data"]
                comments.append({
                    "author": comment_data.get("author", "[deleted]"),
                    "body": comment_data.get("body", ""),
                    "score": comment_data.get("score", 0),
                })

            # Sort by score and return top ones
            comments.sort(key=lambda x: x["score"], reverse=True)
            return comments[:limit]

        except Exception:
            return []


def format_post_with_comments(
    title: str,
    subreddit: str,
    author: str,
    content: str,
    comments: list[dict],
    max_comments: int = 5,
) -> str:
    """Format a post with its top comments for podcast content.

    Args:
        title: Post title
        subreddit: Subreddit name
        author: Post author
        content: Post content/selftext
        comments: List of comment dicts
        max_comments: Max comments to include

    Returns:
        Formatted string for podcast generation
    """
    parts = [
        f"**{title}**",
        f"From r/{subreddit} by {author}",
    ]

    if content:
        parts.append(f"\n{content}")

    if comments:
        parts.append("\n**Top Comments:**")
        for i, comment in enumerate(comments[:max_comments], 1):
            # Truncate long comments
            body = comment["body"]
            if len(body) > 500:
                body = body[:500] + "..."
            parts.append(f"{i}. {comment['author']} ({comment['score']} points): {body}")

    return "\n".join(parts)
