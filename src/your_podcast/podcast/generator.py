"""Podcast episode generator using Podcastfy."""

import random

import os
from pathlib import Path

from podcastfy.client import generate_podcast
from rich.console import Console
from sqlalchemy.orm import Session

from your_podcast.db.models import Episode, Post
from your_podcast.reddit.comment_fetcher import format_post_with_comments
from your_podcast.settings import get_settings

console = Console()


def generate_episode(
    session: Session,
    limit: int = 10,
    subreddits: list[str] | None = None,
    output_dir: str = "./data/podcasts",
    word_count: int = 500,
    sort_by_score: bool = False,
) -> Episode:
    """
    Generate a podcast episode from fetched Reddit posts.

    Selects posts from the database and generates a podcast with Podcastfy.
    All posts include their top comments.

    Args:
        session: Database session
        limit: Maximum number of posts to include in podcast
        subreddits: Optional list of subreddits to filter by
        output_dir: Directory to save audio and transcript files
        word_count: Target word count for podcast transcript (~150 words = 1 min audio)
        sort_by_score: If True, select top posts by engagement (score + comments); otherwise random

    Returns:
        Episode: Created episode record with paths to generated files
    """
    settings = get_settings()

    # Set Podcastfy environment variables
    os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    os.environ["ELEVENLABS_API_KEY"] = settings.elevenlabs_api_key

    # Query unused posts (not yet in an episode)
    query = session.query(Post).filter(Post.episode_id.is_(None))

    if subreddits:
        query = query.filter(Post.subreddit.in_(subreddits))

    if sort_by_score:
        # Get top posts by engagement (score + comments)
        posts = query.order_by((Post.score + Post.num_comments).desc()).limit(limit).all()
        if not posts:
            raise ValueError("No unused posts found to generate podcast from")
        console.print(f"[yellow]Selected top {len(posts)} posts by engagement...[/yellow]")
    else:
        # Fetch extra for random selection
        candidate_posts = query.limit(limit * 3).all()
        if not candidate_posts:
            raise ValueError("No unused posts found to generate podcast from")
        posts = random.sample(candidate_posts, min(limit, len(candidate_posts)))
        console.print(f"[yellow]Selected {len(posts)} random posts from {len(candidate_posts)} available...[/yellow]")

    # Format all posts with their comments
    content_parts = []
    for post in posts:
        comments = post.comments or []
        post_text = format_post_with_comments(
            title=post.title,
            subreddit=post.subreddit,
            author=post.author or "unknown",
            content=post.content or "",
            comments=comments,
            max_comments=5,
        )
        console.print(f"  • {post.title[:60]}... [cyan]({len(comments)} comments)[/cyan]")
        content_parts.append(post_text)

    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Prepare text content for Podcastfy
    text_input = "\n---\n\n".join(content_parts)

    # Log what we're doing
    console.print(f"[yellow]Prepared {len(content_parts)} posts for podcast...[/yellow]")

    # Configure podcast conversation with custom ElevenLabs voices
    # Models: eleven_multilingual_v2 (high quality), eleven_turbo_v2_5 (faster)
    conversation_config = {
        "word_count": word_count,
        "conversation_style": ["casual", "informative"],
        "podcast_name": "Reddit Digest",
        "podcast_tagline": "Your Daily Dose of Reddit",
        "text_to_speech": {
            "elevenlabs": {
                "default_voices": {
                    "question": "okH1aHncYRU2dc9TP3hV",
                    "answer": "WIX8boagHAO6uMUqxXLz",
                },
                "model": "eleven_multilingual_v2",
            },
        },
    }

    # Generate podcast using Podcastfy
    console.print(
        f"[yellow]Generating ~{word_count // 150} minute podcast "
        f"with Podcastfy + ElevenLabs...[/yellow]"
    )

    # Find latest transcript before generation to detect the new one
    transcript_dir = Path("./data/transcripts")
    existing_transcripts = set(transcript_dir.glob("transcript_*.txt")) if transcript_dir.exists() else set()

    audio_path = generate_podcast(
        text=text_input,
        tts_model="elevenlabs",
        llm_model_name="anthropic/claude-sonnet-4-5",
        api_key_label="ANTHROPIC_API_KEY",
        conversation_config=conversation_config,
    )

    # Find the newly created transcript
    transcript_path = ""
    if transcript_dir.exists():
        new_transcripts = set(transcript_dir.glob("transcript_*.txt")) - existing_transcripts
        if new_transcripts:
            transcript_path = str(max(new_transcripts, key=lambda p: p.stat().st_mtime).resolve())

    if not transcript_path:
        console.print("[yellow]Warning: Could not find transcript file[/yellow]")

    if not audio_path:
        raise ValueError("Podcast generation failed - no audio file produced")

    # Resolve audio path to absolute
    audio_path = str(Path(audio_path).resolve())

    # Generate episode title from subreddits
    if subreddits:
        subreddit_list = ", ".join(f"r/{s}" for s in subreddits)
        title = f"Reddit Digest: {subreddit_list}"
    else:
        unique_subreddits = list(set(post.subreddit for post in posts))
        subreddit_list = ", ".join(f"r/{s}" for s in unique_subreddits[:3])
        title = f"Reddit Digest: {subreddit_list}"
        if len(unique_subreddits) > 3:
            title += f" and {len(unique_subreddits) - 3} more"

    # Create episode record
    episode = Episode(
        title=title,
        description=f"Generated from {len(posts)} Reddit posts",
        transcript_path=transcript_path,
        audio_path=audio_path,
        post_count=len(posts),
    )

    session.add(episode)
    session.flush()  # Get episode ID without committing

    # Mark posts as used in this episode
    for post in posts:
        post.episode_id = episode.id

    session.commit()
    session.refresh(episode)

    return episode
