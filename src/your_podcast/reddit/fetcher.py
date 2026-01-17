"""Reddit content fetcher for posts and comments."""

from datetime import datetime, timezone

import praw
from sqlalchemy.orm import Session

from your_podcast.db.models import Post, PostComment


def fetch_subreddit_posts(
    reddit: praw.Reddit,
    subreddit_name: str,
    limit: int = 25,
    time_filter: str = "day",
) -> list[praw.models.Submission]:
    """Fetch top posts from a subreddit.

    Args:
        reddit: Authenticated PRAW Reddit instance
        subreddit_name: Name of the subreddit (without r/)
        limit: Maximum number of posts to fetch
        time_filter: Time filter for top posts (hour, day, week, month, year, all)

    Returns:
        List of PRAW Submission objects
    """
    subreddit = reddit.subreddit(subreddit_name)
    return list(subreddit.top(time_filter=time_filter, limit=limit))


def fetch_post_comments(
    submission: praw.models.Submission,
    limit: int = 10,
) -> list[praw.models.Comment]:
    """Fetch top-level comments from a post.

    Args:
        submission: PRAW Submission object
        limit: Maximum number of comments to fetch

    Returns:
        List of top-level PRAW Comment objects (excluding MoreComments)
    """
    submission.comment_sort = "top"
    submission.comments.replace_more(limit=0)  # Remove "load more" placeholders

    comments = []
    for comment in submission.comments[:limit]:
        if isinstance(comment, praw.models.Comment):
            comments.append(comment)

    return comments


def save_post_to_db(
    session: Session,
    submission: praw.models.Submission,
) -> Post | None:
    """Save a Reddit post to the database.

    Args:
        session: SQLAlchemy session
        submission: PRAW Submission object

    Returns:
        The created Post object, or None if it already exists
    """
    # Check if post already exists
    existing = session.query(Post).filter(Post.reddit_id == submission.id).first()
    if existing:
        return None

    post = Post(
        reddit_id=submission.id,
        subreddit=submission.subreddit.display_name,
        title=submission.title,
        content=submission.selftext or "",
        url=submission.url,
        score=submission.score,
        num_comments=submission.num_comments,
        author=str(submission.author) if submission.author else "[deleted]",
        created_utc=datetime.fromtimestamp(submission.created_utc, tz=timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )
    session.add(post)
    return post


def save_comments_to_db(
    session: Session,
    post: Post,
    comments: list[praw.models.Comment],
) -> list[PostComment]:
    """Save comments to the database.

    Args:
        session: SQLAlchemy session
        post: The parent Post object
        comments: List of PRAW Comment objects

    Returns:
        List of created PostComment objects
    """
    saved_comments = []

    for comment in comments:
        # Check if comment already exists
        existing = session.query(PostComment).filter(
            PostComment.reddit_id == comment.id
        ).first()
        if existing:
            continue

        db_comment = PostComment(
            post_id=post.id,
            reddit_id=comment.id,
            author=str(comment.author) if comment.author else "[deleted]",
            body=comment.body,
            score=comment.score,
            depth=comment.depth,
        )
        session.add(db_comment)
        saved_comments.append(db_comment)

    return saved_comments


def fetch_and_save_subreddit(
    reddit: praw.Reddit,
    session: Session,
    subreddit_name: str,
    post_limit: int = 25,
    comment_limit: int = 10,
) -> tuple[int, int]:
    """Fetch posts and comments from a subreddit and save to database.

    Args:
        reddit: Authenticated PRAW Reddit instance
        session: SQLAlchemy session
        subreddit_name: Name of the subreddit (without r/)
        post_limit: Maximum number of posts to fetch
        comment_limit: Maximum number of comments per post

    Returns:
        Tuple of (new_posts_count, new_comments_count)
    """
    new_posts = 0
    new_comments = 0

    submissions = fetch_subreddit_posts(reddit, subreddit_name, limit=post_limit)

    for submission in submissions:
        post = save_post_to_db(session, submission)

        if post:
            new_posts += 1
            # Fetch and save comments for new posts
            comments = fetch_post_comments(submission, limit=comment_limit)
            saved_comments = save_comments_to_db(session, post, comments)
            new_comments += len(saved_comments)

    return new_posts, new_comments
