"""Podcast episode generator using Podcastfy."""

import os
from pathlib import Path

from podcastfy.client import generate_podcast
from rich.console import Console
from sqlalchemy.orm import Session

from your_podcast.db.models import Episode, Post
from your_podcast.podcast.analyzer import filter_and_score_posts
from your_podcast.reddit.comment_fetcher import fetch_comments, format_post_with_comments
from your_podcast.settings import get_settings

console = Console()


def generate_episode(
    session: Session,
    limit: int = 10,
    subreddits: list[str] | None = None,
    output_dir: str = "./data/podcasts",
    use_smart_fetching: bool = True,
    word_count: int = 500,
) -> Episode:
    """
    Generate a podcast episode from fetched Reddit posts.

    Uses Claude to analyze posts and intelligently fetch full URL content
    for "juicy" posts. All posts are included in the podcast, but Claude
    determines which ones are worth fetching full article content for.

    Args:
        session: Database session
        limit: Maximum number of posts to include in podcast
        subreddits: Optional list of subreddits to filter by
        output_dir: Directory to save audio and transcript files
        use_smart_fetching: If True, use Claude to analyze and fetch URLs for interesting posts
        word_count: Target word count for podcast transcript (~150 words = 1 min audio)

    Returns:
        Episode: Created episode record with paths to generated files
    """
    settings = get_settings()

    # Set Podcastfy environment variables
    os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    os.environ["ELEVENLABS_API_KEY"] = settings.elevenlabs_api_key

    # Query posts from database
    query = session.query(Post).order_by(Post.score.desc(), Post.created_utc.desc())

    if subreddits:
        query = query.filter(Post.subreddit.in_(subreddits))

    candidate_posts = query.limit(limit).all()

    if not candidate_posts:
        raise ValueError("No posts found to generate podcast from")

    posts = candidate_posts

    # Analyze posts to decide which ones to deep-dive
    if use_smart_fetching:
        console.print("[yellow]Analyzing posts with Claude to identify deep-dive candidates...[/yellow]")
        # Analyze posts but don't filter them out
        scored_posts = filter_and_score_posts(posts, min_score=0)  # min_score=0 to keep all

        # Create a map of post to analysis
        post_analysis_map = {post: analysis for post, analysis in scored_posts}

        content_parts = []
        posts_with_comments = 0

        for post in posts:
            analysis = post_analysis_map.get(post, {"score": 0, "should_fetch_url": False, "reasoning": "No analysis"})

            # For juicy posts, fetch comments via JSON API
            if analysis["should_fetch_url"]:
                comments = fetch_comments(post.url, limit=10)
                post_text = format_post_with_comments(
                    title=post.title,
                    subreddit=post.subreddit,
                    author=post.author or "unknown",
                    content=post.content or "",
                    comments=comments,
                    max_comments=5,
                )
                posts_with_comments += 1
                console.print(
                    f"  • {post.title[:60]}... "
                    f"[cyan](score: {analysis['score']}/10, "
                    f"{len(comments)} comments)[/cyan]"
                )
            else:
                # Use RSS content directly (no comments)
                post_text = f"**{post.title}**\n"
                post_text += f"From r/{post.subreddit} by {post.author or 'unknown'}\n"
                if post.content:
                    post_text += f"{post.content}\n"
                console.print(
                    f"  • {post.title[:60]}... "
                    f"[cyan](score: {analysis['score']}/10)[/cyan]"
                )
            content_parts.append(post_text)
    else:
        # Simple mode: no analysis, use RSS content for all posts
        content_parts = []
        posts_with_comments = 0

        for post in posts:
            post_text = f"**{post.title}**\n"
            post_text += f"From r/{post.subreddit} by {post.author or 'unknown'}\n"
            if post.content:
                post_text += f"{post.content}\n"
            content_parts.append(post_text)

    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Prepare text content for Podcastfy
    text_input = "\n---\n\n".join(content_parts)

    # Log what we're doing
    console.print(
        f"[yellow]Prepared {len(content_parts)} posts "
        f"({posts_with_comments} with comments)...[/yellow]"
    )

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
    mode_str = "longform" if word_count > 500 else "standard"
    console.print(
        f"[yellow]Generating ~{word_count // 150} minute podcast "
        f"with Podcastfy + ElevenLabs ({mode_str} mode)...[/yellow]"
    )

    # Find latest transcript before generation to detect the new one
    transcript_dir = Path("./data/transcripts")
    existing_transcripts = set(transcript_dir.glob("transcript_*.txt")) if transcript_dir.exists() else set()

    # Use longform mode for longer podcasts to avoid truncation
    # Longform chunks content and generates in parts, then stitches together
    use_longform = word_count > 500

    audio_path = generate_podcast(
        text=text_input,
        tts_model="elevenlabs",
        llm_model_name="anthropic/claude-sonnet-4-5",
        api_key_label="ANTHROPIC_API_KEY",
        conversation_config=conversation_config,
        longform=use_longform,
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
    session.commit()
    session.refresh(episode)

    return episode
