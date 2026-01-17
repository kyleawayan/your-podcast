"""SQLAdmin admin interface."""

from fastapi import FastAPI
from sqladmin import Admin, ModelView

from your_podcast.db.models import Post, PostComment
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


class PostCommentAdmin(ModelView, model=PostComment):
    """Admin view for PostComment model."""

    name = "Comment"
    name_plural = "Comments"
    icon = "fa-solid fa-comment"

    column_list = [
        PostComment.id,
        PostComment.post_id,
        PostComment.author,
        PostComment.body,
        PostComment.score,
        PostComment.depth,
    ]
    column_searchable_list = [PostComment.author, PostComment.body]
    column_sortable_list = [PostComment.score, PostComment.depth]


def create_app() -> FastAPI:
    """Create FastAPI app with SQLAdmin."""
    app = FastAPI(title="Your Podcast Admin")

    # Create admin interface
    admin = Admin(app, get_engine(), title="Your Podcast Admin")

    # Add views
    admin.add_view(PostAdmin)
    admin.add_view(PostCommentAdmin)

    return app
