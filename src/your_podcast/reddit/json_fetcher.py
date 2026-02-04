"""Fetch Reddit posts and comments via JSON API (no auth required)."""

import time
from datetime import datetime, timezone
from typing import Callable

import requests
from requests import Response
from sqlalchemy.orm import Session

from your_podcast.db.models import Post
from your_podcast.reddit.comment_fetcher import fetch_comments
from your_podcast.settings import get_settings


def adaptive_delay(response: Response, base_delay: float = 6.0) -> float:
    """Calculate delay based on Reddit's rate limit headers.

    Args:
        response: HTTP response with rate limit headers
        base_delay: Base delay in seconds

    Returns:
        Recommended delay in seconds before next request
    """
    # Reddit returns rate limit headers as floats (e.g., "99.0")
    remaining = int(float(response.headers.get("X-Ratelimit-Remaining", 100)))
    reset_seconds = float(response.headers.get("X-Ratelimit-Reset", 60))

    if remaining < 5:
        # Almost out, wait for reset
        return reset_seconds
    elif remaining < 20:
        # Getting low, slow down
        return base_delay * 2
    else:
        return base_delay


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


def fetch_with_retry(
    url: str,
    params: dict,
    headers: dict,
    max_retries: int = 3,
    on_wait: Callable[[int, int], None] | None = None,
) -> Response:
    """Fetch URL with exponential backoff retry on 429 errors.

    Args:
        url: URL to fetch
        params: Query parameters
        headers: Request headers
        max_retries: Maximum number of retries
        on_wait: Optional callback(remaining_seconds, attempt) called each second during wait

    Returns:
        Response object

    Raises:
        RuntimeError: If all retries exhausted
    """
    backoff = 1  # Start with 1 second
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)

            if resp.status_code == 429:
                if attempt < max_retries:
                    # Use Reddit's reset header if available, otherwise exponential backoff
                    reset_seconds = float(resp.headers.get("X-Ratelimit-Reset", backoff))
                    wait_time = max(reset_seconds, backoff)

                    # Countdown sleep with progress updates
                    def on_tick(remaining: int) -> None:
                        if on_wait:
                            on_wait(remaining, attempt + 1)

                    _countdown_sleep(wait_time, on_tick)
                    backoff *= 2  # Double for next attempt
                    continue
                else:
                    resp.raise_for_status()

            resp.raise_for_status()
            return resp

        except requests.RequestException as e:
            last_error = e
            if attempt < max_retries and "429" in str(e):
                def on_tick(remaining: int) -> None:
                    if on_wait:
                        on_wait(remaining, attempt + 1)

                _countdown_sleep(backoff, on_tick)
                backoff *= 2
                continue
            raise

    raise RuntimeError(f"Max retries exhausted: {last_error}")


def fetch_subreddit_json(
    subreddit_name: str,
    sort: str = "hot",
    time_filter: str = "day",
    limit: int = 100,
    on_wait: Callable[[float, int], None] | None = None,
) -> tuple[list[dict], Response | None]:
    """Fetch posts from a subreddit via JSON API.

    Args:
        subreddit_name: Name of the subreddit (without r/)
        sort: Sort type (hot, new, top, rising, controversial)
        time_filter: Time filter for top/controversial (hour, day, week, month, year, all)
        limit: Max posts to fetch (max 100)
        on_wait: Optional callback(wait_seconds, attempt) when rate limited

    Returns:
        Tuple of (list of post dicts, last response for rate limiting)
    """
    settings = get_settings()

    # Build URL
    base_url = f"https://www.reddit.com/r/{subreddit_name}/{sort}.json"
    if limit > 100:
        raise NotImplementedError(
            f"Limit of {limit} exceeds Reddit's max of 100 per request. "
            "Pagination not yet implemented."
        )
    params = {"limit": limit}
    if sort in ("top", "controversial"):
        params["t"] = time_filter

    try:
        resp = fetch_with_retry(
            base_url,
            params=params,
            headers={"User-Agent": settings.user_agent},
            on_wait=on_wait,
        )
        data = resp.json()

        posts = []
        for child in data["data"]["children"]:
            if child["kind"] != "t3":  # t3 = link/post
                continue

            post_data = child["data"]
            posts.append({
                "reddit_id": post_data["id"],
                "subreddit": subreddit_name,
                "title": post_data["title"],
                "content": post_data.get("selftext", ""),
                "url": f"https://www.reddit.com{post_data['permalink']}",
                "author": post_data.get("author", "[deleted]"),
                "score": post_data.get("score", 0),
                "created_utc": datetime.fromtimestamp(
                    post_data["created_utc"], tz=timezone.utc
                ),
            })

        return posts, resp

    except Exception as e:
        raise RuntimeError(f"Failed to fetch r/{subreddit_name}: {e}") from e


def save_json_post_to_db(
    session: Session,
    post_data: dict,
    comments: list[dict],
) -> Post | None:
    """Save a JSON-fetched post to the database.

    Args:
        session: SQLAlchemy session
        post_data: Post data dict from fetch_subreddit_json
        comments: List of comment dicts

    Returns:
        The created Post object, or None if it already exists
    """
    # Check if post already exists
    existing = session.query(Post).filter(Post.reddit_id == post_data["reddit_id"]).first()
    if existing:
        return None

    post = Post(
        reddit_id=post_data["reddit_id"],
        subreddit=post_data["subreddit"],
        title=post_data["title"],
        content=post_data.get("content", ""),
        url=post_data["url"],
        author=post_data.get("author", "[deleted]"),
        score=post_data.get("score", 0),
        created_utc=post_data["created_utc"],
        fetched_at=datetime.now(timezone.utc),
        comments=comments,
    )
    session.add(post)
    return post


def fetch_and_save_subreddit_json(
    session: Session,
    subreddit_name: str,
    sort: str = "hot",
    time_filter: str = "day",
    post_limit: int = 100,
    comment_limit: int = 10,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[int, int, Response | None]:
    """Fetch posts and comments from a subreddit and save to database.

    Args:
        session: SQLAlchemy session
        subreddit_name: Name of the subreddit (without r/)
        sort: Sort type (hot, new, top, rising, controversial)
        time_filter: Time filter for top/controversial posts
        post_limit: Max posts to fetch
        comment_limit: Max comments per post
        on_progress: Optional callback for progress updates

    Returns:
        Tuple of (new_posts_count, total_comments_count, last_response)
    """
    # Create wait callback that updates progress with countdown
    def on_wait(remaining_seconds: int, attempt: int) -> None:
        if on_progress:
            on_progress(f"Reddit is rate limiting us for {remaining_seconds}s (retry {attempt}/3)")

    # Fetch posts
    if on_progress:
        on_progress("fetching posts...")
    posts, last_response = fetch_subreddit_json(
        subreddit_name, sort=sort, time_filter=time_filter, limit=post_limit, on_wait=on_wait
    )

    # Collect all posts with comments first (atomic per subreddit)
    posts_with_comments: list[tuple[dict, list[dict]]] = []
    delay = 6.0  # Base delay - stay under 10 QPM for unauthenticated requests

    # Filter out posts we already have (skip fetching comments for existing posts)
    existing_ids = {
        p.reddit_id
        for p in session.query(Post.reddit_id)
        .filter(Post.reddit_id.in_([p["reddit_id"] for p in posts]))
        .all()
    }
    new_posts_to_fetch = [p for p in posts if p["reddit_id"] not in existing_ids]

    for i, post_data in enumerate(new_posts_to_fetch):
        # Calculate ETA based on remaining posts and delay
        remaining_posts = len(new_posts_to_fetch) - (i + 1)
        eta_seconds = remaining_posts * delay
        eta_str = f"{int(eta_seconds // 60)}m{int(eta_seconds % 60):02d}s"
        if on_progress:
            on_progress(f"fetching comments ({i + 1}/{len(new_posts_to_fetch)}) - ~{eta_str} remaining")

        # Wait before fetching comments (adaptive rate limiting)
        if last_response:
            delay = adaptive_delay(last_response, base_delay=6.0)
        time.sleep(delay)

        # Fetch comments for this post (with rate limit callback)
        comments = fetch_comments(post_data["url"], limit=comment_limit, on_wait=on_wait)
        posts_with_comments.append((post_data, comments))

    # Save all posts atomically after fetching is complete
    if on_progress:
        on_progress("saving to database...")

    new_posts = 0
    total_comments = 0
    for post_data, comments in posts_with_comments:
        post = save_json_post_to_db(session, post_data, comments)
        if post:
            new_posts += 1
            total_comments += len(comments)

    # Commit after each subreddit (atomic per subreddit)
    session.commit()

    return new_posts, total_comments, last_response
