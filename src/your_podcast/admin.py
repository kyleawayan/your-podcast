"""SQLAdmin admin interface."""

from fastapi import FastAPI
from sqladmin import Admin, ModelView

from your_podcast.db.models import Episode, Post
from your_podcast.db.session import get_engine


class PostAdmin(ModelView, model=Post):
    """Admin view for Post model."""

    name = "Post"
    name_plural = "Posts"
    icon = "fa-solid fa-newspaper"

    column_list = [
        Post.id,
        Post.reddit_id,
        Post.subreddit,
        Post.title,
        Post.author,
        Post.score,
        Post.num_comments,
        Post.created_utc,
        Post.fetched_at,
    ]
    column_searchable_list = [Post.title, Post.subreddit, Post.author]
    column_sortable_list = [
        Post.subreddit,
        Post.score,
        Post.num_comments,
        Post.created_utc,
        Post.fetched_at,
    ]
    column_default_sort = [(Post.fetched_at, True)]  # Sort by fetched_at desc


class EpisodeAdmin(ModelView, model=Episode):
    """Admin view for Episode model."""

    name = "Episode"
    name_plural = "Episodes"
    icon = "fa-solid fa-podcast"

    column_list = [
        Episode.id,
        Episode.title,
        Episode.post_count,
        Episode.duration_seconds,
        Episode.created_at,
    ]
    column_details_list = [
        Episode.id,
        Episode.title,
        Episode.description,
        Episode.transcript_path,
        Episode.audio_path,
        Episode.post_count,
        Episode.duration_seconds,
        Episode.created_at,
    ]
    column_searchable_list = [Episode.title, Episode.description]
    column_sortable_list = [Episode.post_count, Episode.created_at]
    column_default_sort = [(Episode.created_at, True)]


def create_app() -> FastAPI:
    """Create FastAPI app with SQLAdmin."""
    app = FastAPI(title="Your Podcast Admin")

    # Create admin interface
    admin = Admin(app, get_engine(), title="Your Podcast Admin")

    # Add views
    admin.add_view(PostAdmin)
    admin.add_view(EpisodeAdmin)

    return app
