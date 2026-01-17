"""Fetch CLI commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from your_podcast.db.models import User, UserSubreddit
from your_podcast.db.session import get_session
from your_podcast.reddit.fetcher import fetch_and_save_subreddit
from your_podcast.reddit.oauth import get_reddit_client

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def fetch(
    ctx: typer.Context,
    limit: int = typer.Option(25, "--limit", "-l", help="Posts per subreddit"),
    comments: int = typer.Option(10, "--comments", "-c", help="Comments per post"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Reddit username"),
) -> None:
    """Fetch posts and comments from configured subreddits."""
    if ctx.invoked_subcommand is not None:
        return

    with get_session() as session:
        # Get user
        if user:
            db_user = session.query(User).filter(User.reddit_username == user).first()
            if not db_user:
                console.print(f"[red]User u/{user} not found.[/red]")
                raise typer.Exit(1)
        else:
            users = session.query(User).all()
            if not users:
                console.print("[red]No authenticated users.[/red]")
                console.print("Run [bold]your-podcast auth login[/bold] first.")
                raise typer.Exit(1)
            if len(users) > 1:
                console.print("[yellow]Multiple users. Specify with --user.[/yellow]")
                raise typer.Exit(1)
            db_user = users[0]

        # Get subreddits
        subs = (
            session.query(UserSubreddit)
            .filter(UserSubreddit.user_id == db_user.id)
            .all()
        )

        if not subs:
            console.print(f"[yellow]No subreddits configured for u/{db_user.reddit_username}.[/yellow]")
            console.print("Run [bold]your-podcast config add <subreddit>[/bold] first.")
            raise typer.Exit(1)

        # Get Reddit client
        try:
            reddit = get_reddit_client(db_user.refresh_token)
        except Exception as e:
            console.print(f"[red]Failed to connect to Reddit:[/red] {e}")
            raise typer.Exit(1)

        console.print(f"[bold]Fetching from {len(subs)} subreddit(s) for u/{db_user.reddit_username}...[/bold]")

        total_posts = 0
        total_comments = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for sub in subs:
                task = progress.add_task(f"r/{sub.subreddit}", total=None)

                try:
                    new_posts, new_comments = fetch_and_save_subreddit(
                        reddit=reddit,
                        session=session,
                        subreddit_name=sub.subreddit,
                        post_limit=limit,
                        comment_limit=comments,
                    )
                    total_posts += new_posts
                    total_comments += new_comments
                    progress.update(task, description=f"r/{sub.subreddit} [green]✓[/green] ({new_posts} posts, {new_comments} comments)")
                except Exception as e:
                    progress.update(task, description=f"r/{sub.subreddit} [red]✗[/red] {e}")

                progress.update(task, completed=True)

        console.print(f"\n[green]Done![/green] Fetched {total_posts} new posts and {total_comments} new comments.")
