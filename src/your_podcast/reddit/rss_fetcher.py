"""Reddit RSS feed fetcher."""

from datetime import datetime, timezone
from html import unescape

import feedparser
from sqlalchemy.orm import Session

from your_podcast.db.models import Post
from your_podcast.settings import get_settings


def fetch_subreddit_rss(
    subreddit_name: str,
    sort: str = "hot",
    time_filter: str = "day",
) -> list[dict]:
    """Fetch posts from a subreddit via RSS.

    Args:
        subreddit_name: Name of the subreddit (without r/)
        sort: Sort type (hot, new, top, rising)
        time_filter: Time filter for top posts (hour, day, week, month, year, all)

    Returns:
        List of post dictionaries
    """
    settings = get_settings()

    # Build RSS URL
    # Sorts: hot, new, top, rising, controversial
    if sort in ("top", "controversial"):
        url = f"https://www.reddit.com/r/{subreddit_name}/{sort}/.rss?t={time_filter}"
    else:
        url = f"https://www.reddit.com/r/{subreddit_name}/{sort}/.rss"

    # Fetch the RSS feed
    feed = feedparser.parse(url, agent=settings.user_agent)

    posts = []
    for entry in feed.entries:
        # Extract Reddit ID from the entry link
        # Format: https://www.reddit.com/r/subreddit/comments/REDDIT_ID/title/
        parts = entry.link.split("/")
        reddit_id = parts[6] if len(parts) > 6 else entry.id.split("_")[-1]

        # Parse the content HTML to get selftext
        content_html = entry.get("content", [{}])[0].get("value", "")
        # Simple HTML stripping (unescape HTML entities)
        content = unescape(content_html)

        posts.append(
            {
                "reddit_id": reddit_id,
                "subreddit": subreddit_name,
                "title": entry.title,
                "content": content,
                "url": entry.link,
                "author": entry.author if hasattr(entry, "author") else "[unknown]",
                "created_utc": datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc),
            }
        )

    return posts


def save_rss_post_to_db(
    session: Session,
    post_data: dict,
) -> Post | None:
    """Save an RSS post to the database.

    Args:
        session: SQLAlchemy session
        post_data: Dictionary with post data from RSS

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
        author=post_data.get("author", "[unknown]"),
        score=0,  # RSS doesn't provide score
        num_comments=0,  # RSS doesn't provide comment count
        created_utc=post_data["created_utc"],
        fetched_at=datetime.now(timezone.utc),
    )
    session.add(post)
    return post


def fetch_and_save_subreddit_rss(
    session: Session,
    subreddit_name: str,
    sort: str = "hot",
    time_filter: str = "day",
) -> int:
    """Fetch posts from a subreddit RSS and save to database.

    Args:
        session: SQLAlchemy session
        subreddit_name: Name of the subreddit (without r/)
        sort: Sort type (hot, new, top, rising)
        time_filter: Time filter for top posts

    Returns:
        Number of new posts saved
    """
    posts = fetch_subreddit_rss(subreddit_name, sort=sort, time_filter=time_filter)

    new_posts = 0
    for post_data in posts:
        post = save_rss_post_to_db(session, post_data)
        if post:
            new_posts += 1

    return new_posts
