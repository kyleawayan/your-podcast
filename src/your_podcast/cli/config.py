"""Configuration CLI commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from your_podcast.db.models import User, UserSubreddit
from your_podcast.db.session import get_session

app = typer.Typer()
console = Console()


def get_current_user(session, username: Optional[str] = None) -> User:
    """Get the current user, or the only user if there's just one."""
    if username:
        user = session.query(User).filter(User.reddit_username == username).first()
        if not user:
            console.print(f"[red]User u/{username} not found.[/red]")
            raise typer.Exit(1)
        return user

    users = session.query(User).all()
    if not users:
        console.print("[red]No authenticated users.[/red]")
        console.print("Run [bold]your-podcast auth login[/bold] first.")
        raise typer.Exit(1)

    if len(users) == 1:
        return users[0]

    console.print("[yellow]Multiple users found. Please specify with --user.[/yellow]")
    for user in users:
        console.print(f"  - u/{user.reddit_username}")
    raise typer.Exit(1)


@app.command("add")
def add_subreddits(
    subreddits: list[str] = typer.Argument(..., help="Subreddits to add (without r/)"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Reddit username"),
) -> None:
    """Add subreddits to follow."""
    with get_session() as session:
        db_user = get_current_user(session, user)

        added = []
        existing = []

        for subreddit in subreddits:
            # Normalize subreddit name (remove r/ prefix if present)
            name = subreddit.lower().removeprefix("r/")

            # Check if already following
            exists = (
                session.query(UserSubreddit)
                .filter(
                    UserSubreddit.user_id == db_user.id,
                    UserSubreddit.subreddit == name,
                )
                .first()
            )

            if exists:
                existing.append(name)
            else:
                session.add(UserSubreddit(user_id=db_user.id, subreddit=name))
                added.append(name)

        if added:
            console.print(f"[green]Added:[/green] {', '.join(f'r/{s}' for s in added)}")
        if existing:
            console.print(
                f"[yellow]Already following:[/yellow] {', '.join(f'r/{s}' for s in existing)}"
            )


@app.command("list")
def list_subreddits(
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Reddit username"),
) -> None:
    """List configured subreddits."""
    with get_session() as session:
        db_user = get_current_user(session, user)

        subs = (
            session.query(UserSubreddit)
            .filter(UserSubreddit.user_id == db_user.id)
            .order_by(UserSubreddit.subreddit)
            .all()
        )

        if not subs:
            console.print(f"[yellow]No subreddits configured for u/{db_user.reddit_username}.[/yellow]")
            console.print("Run [bold]your-podcast config add <subreddit>[/bold] to add some.")
            return

        table = Table(title=f"Subreddits for u/{db_user.reddit_username}")
        table.add_column("Subreddit", style="cyan")

        for sub in subs:
            table.add_row(f"r/{sub.subreddit}")

        console.print(table)


@app.command("remove")
def remove_subreddits(
    subreddits: list[str] = typer.Argument(..., help="Subreddits to remove"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Reddit username"),
) -> None:
    """Remove subreddits from following."""
    with get_session() as session:
        db_user = get_current_user(session, user)

        removed = []
        not_found = []

        for subreddit in subreddits:
            name = subreddit.lower().removeprefix("r/")

            sub = (
                session.query(UserSubreddit)
                .filter(
                    UserSubreddit.user_id == db_user.id,
                    UserSubreddit.subreddit == name,
                )
                .first()
            )

            if sub:
                session.delete(sub)
                removed.append(name)
            else:
                not_found.append(name)

        if removed:
            console.print(f"[green]Removed:[/green] {', '.join(f'r/{s}' for s in removed)}")
        if not_found:
            console.print(
                f"[yellow]Not found:[/yellow] {', '.join(f'r/{s}' for s in not_found)}"
            )
