"""Podcast episode generator using Podcastfy."""

import random
from datetime import datetime
from pathlib import Path

from podcastfy.client import generate_podcast
from rich.console import Console
from sqlalchemy.orm import Session

from your_podcast.db.models import Episode, Post, User
from your_podcast.podcast.chatterbox_tts import generate_audio_chatterbox
from your_podcast.podcast.google_cloud_tts import generate_audio_google_cloud
from your_podcast.podcast.macos_tts import generate_audio_macos
from your_podcast.reddit.comment_fetcher import format_post_with_comments
from your_podcast.settings import get_settings

console = Console()

# Transcript directory used by Podcastfy
TRANSCRIPT_DIR = Path("./data/transcripts")


def _find_new_transcript(existing: set[Path]) -> str | None:
    """Find newly created transcript file.

    Args:
        existing: Set of transcript paths that existed before generation.

    Returns:
        Absolute path to the new transcript, or None if not found.
    """
    if not TRANSCRIPT_DIR.exists():
        return None
    new = set(TRANSCRIPT_DIR.glob("transcript_*.txt")) - existing
    if new:
        return str(max(new, key=lambda p: p.stat().st_mtime).resolve())
    return None


def _get_existing_transcripts() -> set[Path]:
    """Get set of existing transcript files before generation."""
    if TRANSCRIPT_DIR.exists():
        return set(TRANSCRIPT_DIR.glob("transcript_*.txt"))
    return set()


def generate_episode(
    session: Session,
    limit: int = 10,
    subreddits: list[str] | None = None,
    output_dir: str = "./data/podcasts",
    longform: bool = True,
    sort_by_score: bool = False,
    tts_backend: str | None = None,
    include_covered_posts: bool = False,
    user: User | None = None,
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
        longform: If True, use longform mode for complete coverage (default).
                  If False, use shortform mode (faster but may truncate).
        sort_by_score: If True, select top posts by engagement (score + comments); otherwise random
        tts_backend: TTS backend to use ("elevenlabs" or "macos"). Defaults to settings.
        include_covered_posts: If True, include posts already covered in previous episodes.
        user: User to generate episode for. Required.

    Returns:
        Episode: Created episode record with paths to generated files
    """
    if user is None:
        raise ValueError("User is required for episode generation")

    settings = get_settings()
    tts_backend = tts_backend or settings.tts_backend
    # Podcastfy picks up API keys from environment variables automatically

    # Query posts
    query = session.query(Post)
    if not include_covered_posts:
        # Only exclude posts covered by THIS user's episodes
        query = query.filter(~Post.episodes.any(Episode.user_id == user.id))

    if subreddits:
        query = query.filter(Post.subreddit.in_(subreddits))

    if sort_by_score:
        # Get top posts by score
        posts = query.order_by(Post.score.desc()).limit(limit).all()
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

    # Configure podcast conversation
    today = datetime.now()
    tagline = f"Your personalized podcast just for you, for the day of {today.strftime('%B')} {today.day}, {today.year}"
    conversation_config = {
        "conversation_style": ["casual", "informative", "enthusiastic"],
        "podcast_name": "Your Podcast",
        "podcast_tagline": tagline,
        "dialogue_structure": ["Introduction", "Main Content Summary", "Conclusion"],
        "roles_person1": "main host who introduces topics and drives the conversation",
        "roles_person2": "co-host who adds commentary, asks questions, and provides different perspectives",
    }

    if tts_backend == "elevenlabs":
        # ElevenLabs voices config
        # Models: eleven_multilingual_v2 (high quality), eleven_turbo_v2_5 (faster)
        conversation_config["text_to_speech"] = {
            "elevenlabs": {
                "default_voices": {
                    "question": settings.elevenlabs_voice_1,
                    "answer": settings.elevenlabs_voice_2,
                },
                "model": "eleven_multilingual_v2",
            },
        }

        mode_str = "longform" if longform else "shortform"
        console.print(f"[yellow]Generating podcast with Podcastfy + ElevenLabs ({mode_str})...[/yellow]")

        existing_transcripts = _get_existing_transcripts()

        audio_path = generate_podcast(
            text=text_input,
            tts_model="elevenlabs",
            llm_model_name="gemini-2.5-flash",
            api_key_label="GEMINI_API_KEY",
            conversation_config=conversation_config,
            longform=longform,
        )

        transcript_path = _find_new_transcript(existing_transcripts) or ""
        if not transcript_path:
            console.print("[yellow]Warning: Could not find transcript file[/yellow]")

        if not audio_path:
            raise ValueError("Podcast generation failed - no audio file produced")

    elif tts_backend == "macos":
        mode_str = "longform" if longform else "shortform"
        console.print(f"[yellow]Generating podcast with Podcastfy + macOS voices ({mode_str})...[/yellow]")

        existing_transcripts = _get_existing_transcripts()

        # Generate transcript only (no TTS) using Podcastfy
        generate_podcast(
            text=text_input,
            tts_model="elevenlabs",
            llm_model_name="gemini-2.5-flash",
            api_key_label="GEMINI_API_KEY",
            conversation_config=conversation_config,
            transcript_only=True,
            longform=longform,
        )

        transcript_path = _find_new_transcript(existing_transcripts)
        if not transcript_path:
            raise ValueError("Podcast generation failed - no transcript file produced")

        # Read the transcript content
        transcript_text = Path(transcript_path).read_text()

        # Generate audio with macOS say command
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_file = str(output_path / f"podcast_{user.name}_{timestamp}.mp3")

        audio_path = generate_audio_macos(
            transcript=transcript_text,
            voice_1=settings.macos_voice_1,
            voice_2=settings.macos_voice_2,
            output_path=audio_file,
        )

    elif tts_backend == "chatterbox":
        mode_str = "longform" if longform else "shortform"
        console.print(f"[yellow]Generating podcast with Podcastfy + Chatterbox ({mode_str})...[/yellow]")

        existing_transcripts = _get_existing_transcripts()

        # Generate transcript only (no TTS) using Podcastfy
        generate_podcast(
            text=text_input,
            tts_model="elevenlabs",
            llm_model_name="gemini-2.5-flash",
            api_key_label="GEMINI_API_KEY",
            conversation_config=conversation_config,
            transcript_only=True,
            longform=longform,
        )

        transcript_path = _find_new_transcript(existing_transcripts)
        if not transcript_path:
            raise ValueError("Podcast generation failed - no transcript file produced")

        # Read the transcript content
        transcript_text = Path(transcript_path).read_text()

        # Generate audio with Chatterbox-Turbo
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_file = str(output_path / f"podcast_{user.name}_{timestamp}.mp3")

        audio_path = generate_audio_chatterbox(
            transcript=transcript_text,
            voice_1_ref=settings.chatterbox_voice_1,
            voice_2_ref=settings.chatterbox_voice_2,
            output_path=audio_file,
        )

    elif tts_backend == "google_cloud":
        mode_str = "longform" if longform else "shortform"
        console.print(f"[yellow]Generating podcast with Podcastfy + Google Cloud TTS ({mode_str})...[/yellow]")

        existing_transcripts = _get_existing_transcripts()

        # Generate transcript only (no TTS) using Podcastfy
        generate_podcast(
            text=text_input,
            tts_model="elevenlabs",
            llm_model_name="gemini-2.5-flash",
            api_key_label="GEMINI_API_KEY",
            conversation_config=conversation_config,
            transcript_only=True,
            longform=longform,
        )

        transcript_path = _find_new_transcript(existing_transcripts)
        if not transcript_path:
            raise ValueError("Podcast generation failed - no transcript file produced")

        # Read the transcript content
        transcript_text = Path(transcript_path).read_text()

        # Generate audio with Google Cloud TTS
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_file = str(output_path / f"podcast_{user.name}_{timestamp}.mp3")

        audio_path = generate_audio_google_cloud(
            transcript=transcript_text,
            voice_1=settings.google_cloud_voice_1,
            voice_2=settings.google_cloud_voice_2,
            output_path=audio_file,
            model=settings.google_cloud_model,
        )

    else:
        raise ValueError(f"Unknown TTS backend: {tts_backend}. Use 'elevenlabs', 'macos', 'chatterbox', or 'google_cloud'.")

    # Resolve audio path to absolute
    audio_path = str(Path(audio_path).resolve())

    # Generate episode title from subreddits
    if subreddits:
        subreddit_list = ", ".join(f"r/{s}" for s in subreddits)
        title = f"Your Podcast ({user.name}): {subreddit_list}"
    else:
        unique_subreddits = list(set(post.subreddit for post in posts))
        subreddit_list = ", ".join(f"r/{s}" for s in unique_subreddits[:3])
        title = f"Your Podcast ({user.name}): {subreddit_list}"
        if len(unique_subreddits) > 3:
            title += f" and {len(unique_subreddits) - 3} more"

    # Create episode record
    episode = Episode(
        title=title,
        description=f"Generated from {len(posts)} Reddit posts",
        transcript_path=transcript_path,
        audio_path=audio_path,
        post_count=len(posts),
        user=user,
    )

    session.add(episode)
    session.flush()  # Get episode ID without committing

    # Mark posts as used in this episode
    for post in posts:
        post.episodes.append(episode)

    session.commit()
    session.refresh(episode)

    return episode
