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


def log_generation(
    post_count: int,
    word_count: int,
    render_seconds: float,
    llm_model: str,
    tts_model: str,
) -> None:
    """Append generation stats to the log file."""
    commit, dirty = get_git_info()
    row = {
        "commit_hash": commit,
        "dirty": dirty,
        "post_count": post_count,
        "word_count": word_count,
        "llm_model": llm_model,
        "tts_model": tts_model,
        "render_seconds": round(render_seconds, 1),
    }

    file_exists = LOG_FILE.exists()
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
from your_podcast.reddit.rss_fetcher import fetch_and_save_subreddit_rss

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
) -> None:
    """Fetch posts from Reddit subreddits via RSS."""
    console.print(f"[bold]Fetching from {len(subreddits)} subreddit(s)...[/bold]")

    total_posts = 0

    with get_session() as session:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for subreddit in subreddits:
                # Normalize subreddit name
                name = subreddit.lower().removeprefix("r/")
                task = progress.add_task(f"r/{name}", total=None)

                try:
                    new_posts = fetch_and_save_subreddit_rss(
                        session=session,
                        subreddit_name=name,
                        sort=sort,
                        time_filter=time_filter,
                    )
                    total_posts += new_posts
                    progress.update(
                        task,
                        description=f"r/{name} [green]✓[/green] ({new_posts} new posts)",
                    )
                except Exception as e:
                    progress.update(task, description=f"r/{name} [red]✗[/red] {e}")

                progress.update(task, completed=True)

    console.print(f"\n[green]Done![/green] Fetched {total_posts} new posts.")


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


@app.command()
def generate(
    limit: int = typer.Option(10, "--limit", "-l", help="Number of posts to include"),
    subreddits: list[str] = typer.Option(
        None, "--subreddit", "-s", help="Filter by specific subreddits"
    ),
    output_dir: str = typer.Option(
        "./data/podcasts", "--output", "-o", help="Output directory for podcast files"
    ),
    no_smart_fetch: bool = typer.Option(
        False, "--no-smart-fetch", help="Disable Claude analysis and URL fetching"
    ),
    word_count: int = typer.Option(
        500, "--words", "-w", help="Target word count (~150 words = 1 min audio)"
    ),
) -> None:
    """Generate a podcast episode from fetched Reddit posts.

    Uses Claude to analyze posts and intelligently fetch full article content
    for "juicy" posts. All posts are included, but only interesting ones get
    deep-dived with full URL content. Disable with --no-smart-fetch for faster generation.

    Default is ~3.5 minutes. Use --words 750 for ~5 minutes.
    """
    console.print("[bold]Generating podcast episode...[/bold]")
    start_time = time.time()

    with get_session() as session:
        try:
            episode = generate_episode(
                session=session,
                limit=limit,
                subreddits=subreddits,
                output_dir=output_dir,
                use_smart_fetching=not no_smart_fetch,
                word_count=word_count,
            )
            render_seconds = time.time() - start_time

            console.print(f"\n[green]Success![/green] Podcast episode generated:")
            console.print(f"  Title: {episode.title}")
            console.print(f"  Description: {episode.description}")
            console.print(f"  Posts: {episode.post_count}")
            console.print(f"  Transcript: {episode.transcript_path}")
            console.print(f"  Audio: {episode.audio_path}")
            console.print(f"  Render time: {render_seconds:.1f}s")

            # Log stats for optimization tracking
            log_generation(
                post_count=episode.post_count,
                word_count=word_count,
                render_seconds=render_seconds,
                llm_model="claude-sonnet-4-5",
                tts_model="eleven_multilingual_v2",
            )

        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)
        except Exception as e:
            console.print(f"[red]Failed to generate podcast:[/red] {e}")
            raise typer.Exit(1)


if __name__ == "__main__":
    app()
