"""Main CLI entry point for Your Podcast."""

import csv
import subprocess
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from your_podcast.db.session import get_session

LOG_FILE = Path(__file__).parent.parent.parent.parent / "generation_log.csv"

from your_podcast.podcast.generator import generate_episode


def get_git_info() -> tuple[str, bool]:
    """Get the current git commit hash and dirty status."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        commit = result.stdout.strip()

        # Check if repo is dirty
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        dirty = bool(status.stdout.strip())

        return commit, dirty
    except Exception:
        return "unknown", False


def get_audio_duration(audio_path: str) -> float | None:
    """Get audio duration in seconds using afinfo (macOS)."""
    try:
        result = subprocess.run(
            ["afinfo", audio_path],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            if "estimated duration" in line:
                # Format: "estimated duration: 599.248980 sec"
                return float(line.split(":")[1].strip().split()[0])
    except Exception:
        pass
    return None


def log_generation(
    post_count: int,
    render_seconds: float,
    llm_model: str,
    tts_model: str,
    longform: bool,
    duration_seconds: float | None = None,
) -> None:
    """Append generation stats to the log file."""
    commit, dirty = get_git_info()
    row = {
        "commit_hash": commit,
        "dirty": dirty,
        "post_count": post_count,
        "word_count": -1,  # Deprecated, kept for CSV compatibility
        "llm_model": llm_model,
        "tts_model": tts_model,
        "render_seconds": round(render_seconds, 1),
        "longform": longform,
        "duration_seconds": round(duration_seconds, 1) if duration_seconds else "",
    }

    file_exists = LOG_FILE.exists()
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
from your_podcast.reddit.json_fetcher import adaptive_delay, fetch_and_save_subreddit_json

app = typer.Typer(
    name="your-podcast",
    help="Generate personalized podcasts from Reddit content.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def fetch(
    subreddits: list[str] = typer.Argument(
        ..., help="Subreddits to fetch from (e.g., python rust programming)"
    ),
    sort: str = typer.Option("hot", "--sort", "-s", help="Sort type (hot, new, top, rising)"),
    time_filter: str = typer.Option(
        "day", "--time", "-t", help="Time filter for top posts (hour, day, week, month, year, all)"
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Posts per subreddit (max 100)"),
    comment_limit: int = typer.Option(10, "--comments", "-c", help="Comments per post"),
) -> None:
    """Fetch posts and comments from Reddit subreddits via JSON API."""
    # Estimate max time (assumes all posts are new - actual time may be less)
    max_posts = len(subreddits) * limit
    estimated_seconds = max_posts * 6  # 6 seconds per request (10 QPM rate limit)
    hours, remainder = divmod(int(estimated_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        eta_str = f"~{hours}h {minutes}m max"
    elif minutes > 0:
        eta_str = f"~{minutes}m {seconds}s max"
    else:
        eta_str = f"~{seconds}s max"
    console.print(f"[bold]Fetching from {len(subreddits)} subreddit(s)...[/bold] ({eta_str})")

    total_posts = 0
    total_comments = 0
    last_response = None

    with get_session() as session:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for i, subreddit in enumerate(subreddits):
                # Wait between subreddits (adaptive rate limiting)
                if last_response and i > 0:
                    delay = adaptive_delay(last_response, base_delay=1.0)
                    time.sleep(delay)

                # Normalize subreddit name
                name = subreddit.lower().removeprefix("r/")
                task = progress.add_task(f"r/{name}: starting...", total=None)

                def update_progress(status: str) -> None:
                    progress.update(task, description=f"r/{name}: {status}")

                try:
                    new_posts, new_comments, last_response = fetch_and_save_subreddit_json(
                        session=session,
                        subreddit_name=name,
                        sort=sort,
                        time_filter=time_filter,
                        post_limit=limit,
                        comment_limit=comment_limit,
                        on_progress=update_progress,
                    )
                    total_posts += new_posts
                    total_comments += new_comments
                    progress.update(
                        task,
                        description=f"r/{name} [green]✓[/green] ({new_posts} posts, {new_comments} comments)",
                    )
                except Exception as e:
                    progress.update(task, description=f"r/{name} [red]✗[/red] {e}")

                progress.update(task, completed=True)

    console.print(f"\n[green]Done![/green] Fetched {total_posts} new posts with {total_comments} comments.")


@app.command()
def clear(
    posts: bool = typer.Option(False, "--posts", help="Clear all posts"),
    episodes: bool = typer.Option(False, "--episodes", help="Clear all episodes"),
    all: bool = typer.Option(False, "--all", help="Clear everything"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Clear data from the database."""
    from your_podcast.db.models import Episode, Post

    if not (posts or episodes or all):
        console.print("[red]Error:[/red] Specify what to clear: --posts, --episodes, or --all")
        raise typer.Exit(1)

    with get_session() as session:
        if all or posts:
            count = session.query(Post).count()
            if not force:
                confirm = typer.confirm(f"Delete {count} posts?")
                if not confirm:
                    console.print("Cancelled.")
                    raise typer.Exit(0)

            session.query(Post).delete()
            console.print(f"[green]Deleted {count} posts[/green]")

        if all or episodes:
            count = session.query(Episode).count()
            if not force:
                confirm = typer.confirm(f"Delete {count} episodes?")
                if not confirm:
                    console.print("Cancelled.")
                    raise typer.Exit(0)

            # Clear post-episode associations before deleting episodes
            from your_podcast.db.models import post_episodes

            result = session.execute(post_episodes.delete())
            if result.rowcount > 0:
                console.print(f"[green]Cleared {result.rowcount} post-episode associations[/green]")

            session.query(Episode).delete()
            console.print(f"[green]Deleted {count} episodes[/green]")


@app.command()
def admin(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind to"),
) -> None:
    """Start the SQLAdmin web interface."""
    import uvicorn

    from your_podcast.admin import create_app

    console.print(f"[bold]Starting admin interface at http://{host}:{port}/admin[/bold]")
    console.print("Press Ctrl+C to stop")

    app = create_app()
    uvicorn.run(app, host=host, port=port)


# Duration estimates per post (based on historical data)
SECONDS_PER_POST_LONGFORM = 180  # ~3 min/post in longform mode
SECONDS_PER_POST_SHORTFORM = 50  # ~50 sec/post in shortform mode


def get_or_create_user(session, name: str):
    """Get user by name, creating if it doesn't exist."""
    from your_podcast.db.models import User

    user = session.query(User).filter(User.name == name).first()
    if not user:
        user = User(name=name)
        session.add(user)
        session.flush()  # Get the ID without committing
    return user


@app.command()
def generate(
    limit: int = typer.Option(None, "--limit", "-l", help="Number of posts to include"),
    duration: int = typer.Option(None, "--duration", "-d", help="Target duration in minutes"),
    subreddits: list[str] = typer.Option(
        None, "--subreddit", "-s", help="Filter by specific subreddits"
    ),
    output_dir: str = typer.Option(
        "./data/podcasts", "--output", "-o", help="Output directory for podcast files"
    ),
    shortform: bool = typer.Option(
        False, "--shortform", help="Shorter podcast (2-5 min); may truncate with many posts"
    ),
    by_engagement: bool = typer.Option(
        False, "--by-engagement", help="Select top posts by engagement (score + comments)"
    ),
    tts: str = typer.Option(
        None, "--tts", help="TTS backend: 'elevenlabs' or 'macos' (default from settings)"
    ),
    include_covered_posts: bool = typer.Option(
        False, "--include-covered-posts", help="Include posts already covered in previous episodes"
    ),
    user: str = typer.Option(
        "global", "--user", "-u", help="User name for this episode (for tracking covered posts)"
    ),
) -> None:
    """Generate a podcast episode from fetched Reddit posts.

    Selects unused posts (random by default, or top by engagement with --by-engagement)
    and generates a podcast with Podcastfy. Posts are marked as used after generation.

    Specify either --limit (number of posts) or --duration (target minutes), not both.
    Default: 5 posts (~15 minutes).

    Uses longform mode by default for complete coverage of all posts.
    Use --shortform for faster generation (may truncate with many posts).

    Use --tts macos to use free macOS Premium/Siri voices instead of ElevenLabs.
    """
    # Validate mutually exclusive options
    if limit is not None and duration is not None:
        console.print("[red]Error:[/red] Specify either --limit or --duration, not both")
        raise typer.Exit(1)

    # Calculate post limit from duration or use default
    if duration is not None:
        limit = max(1, round(duration * 60 / SECONDS_PER_POST_LONGFORM))
        estimated_duration = limit * SECONDS_PER_POST_LONGFORM / 60
        console.print(f"[bold]Target: {duration} min → using {limit} posts (est. ~{estimated_duration:.0f} min)[/bold]")
    elif limit is None:
        limit = 5  # Default

    estimated_duration = limit * SECONDS_PER_POST_LONGFORM / 60
    console.print(f"[bold]Generating podcast episode (~{estimated_duration:.0f} min from {limit} posts) for user '{user}'...[/bold]")
    start_time = time.time()

    longform = not shortform

    with get_session() as session:
        # Get or create user
        user_obj = get_or_create_user(session, user)

        try:
            episode = generate_episode(
                session=session,
                limit=limit,
                subreddits=subreddits,
                output_dir=output_dir,
                longform=longform,
                sort_by_score=by_engagement,
                tts_backend=tts,
                include_covered_posts=include_covered_posts,
                user=user_obj,
            )
            render_seconds = time.time() - start_time

            # Get actual audio duration and save to database
            duration_seconds = get_audio_duration(episode.audio_path)
            if duration_seconds:
                episode.duration_seconds = int(duration_seconds)
                session.commit()
            duration_str = f"{duration_seconds / 60:.1f} min" if duration_seconds else "unknown"

            console.print(f"\n[green]Success![/green] Podcast episode generated:")
            console.print(f"  Title: {episode.title}")
            console.print(f"  Description: {episode.description}")
            console.print(f"  Posts: {episode.post_count}")
            console.print(f"  Duration: {duration_str}")
            console.print(f"  Transcript: {episode.transcript_path}")
            console.print(f"  Audio: {episode.audio_path}")
            console.print(f"  Render time: {render_seconds:.1f}s")

            # Log stats for optimization tracking
            from your_podcast.settings import get_settings
            effective_tts = tts or get_settings().tts_backend
            tts_model_map = {
                "macos": "macos_say",
                "chatterbox": "chatterbox_turbo",
                "elevenlabs": "eleven_multilingual_v2",
            }
            log_generation(
                post_count=episode.post_count,
                render_seconds=render_seconds,
                llm_model="gemini-2.5-flash",
                tts_model=tts_model_map.get(effective_tts, effective_tts),
                longform=longform,
                duration_seconds=duration_seconds,
            )

        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)
        except Exception as e:
            console.print(f"[red]Failed to generate podcast:[/red] {e}")
            raise typer.Exit(1)


@app.command("test-voices")
def test_voices(
    play: bool = typer.Option(False, "--play", "-p", help="Play each audio file after generation"),
) -> None:
    """Test TTS voice providers with a sample transcript.

    Generates short audio clips using all configured providers (macOS + ElevenLabs)
    and saves them to data/test_audio/ for manual comparison.
    """
    from your_podcast.podcast.voice_tester import run_all_tests

    console.print("[bold]Running voice tests...[/bold]\n")
    results = run_all_tests()

    console.print("\n[bold]Results:[/bold]")
    for provider, path in results.items():
        if path:
            console.print(f"  [green]{provider}:[/green] {path}")
        else:
            console.print(f"  [yellow]{provider}:[/yellow] skipped or failed")

    if play:
        console.print("\n[bold]Playback:[/bold]")
        console.print("[dim]Press Enter to play each file, Ctrl+C to exit[/dim]\n")

        for provider, path in results.items():
            if not path:
                continue

            try:
                input(f"[{provider}] Press Enter to play...")
                console.print(f"[cyan]Playing {provider}...[/cyan]")
                subprocess.run(["afplay", str(path)], check=True)
            except KeyboardInterrupt:
                console.print("\n[yellow]Playback cancelled[/yellow]")
                break


if __name__ == "__main__":
    app()
