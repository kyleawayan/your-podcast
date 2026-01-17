"""Fetch Reddit comments via JSON API (no auth required)."""

import time

import requests

from your_podcast.settings import get_settings


def fetch_comments(reddit_url: str, limit: int = 10) -> list[dict]:
    """Fetch top comments from a Reddit post via JSON API.

    Args:
        reddit_url: Full Reddit post URL
        limit: Max number of comments to fetch

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

    try:
        resp = requests.get(
            json_url,
            headers={"User-Agent": settings.user_agent},
            timeout=10,
        )
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
