"""Main CLI entry point for Your Podcast."""

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from your_podcast.db.session import get_session
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


if __name__ == "__main__":
    app()
