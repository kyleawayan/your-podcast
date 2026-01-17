"""Authentication CLI commands."""

import typer
from rich.console import Console

from your_podcast.db.models import User
from your_podcast.db.session import get_session
from your_podcast.reddit.oauth import start_oauth_flow, get_reddit_client

app = typer.Typer()
console = Console()


@app.command()
def login() -> None:
    """Authenticate with Reddit via OAuth."""
    console.print("[bold]Starting Reddit OAuth flow...[/bold]")

    try:
        refresh_token, username = start_oauth_flow()
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # Save user to database
    with get_session() as session:
        # Check if user already exists
        existing = session.query(User).filter(User.reddit_username == username).first()

        if existing:
            # Update the refresh token
            existing.refresh_token = refresh_token
            console.print(f"[green]Updated credentials for u/{username}[/green]")
        else:
            # Create new user
            user = User(reddit_username=username, refresh_token=refresh_token)
            session.add(user)
            console.print(f"[green]Successfully authenticated as u/{username}[/green]")


@app.command()
def status() -> None:
    """Show current authentication status."""
    with get_session() as session:
        users = session.query(User).all()

        if not users:
            console.print("[yellow]No authenticated users.[/yellow]")
            console.print("Run [bold]your-podcast auth login[/bold] to authenticate.")
            return

        console.print("[bold]Authenticated users:[/bold]")
        for user in users:
            # Verify the token still works
            try:
                reddit = get_reddit_client(user.refresh_token)
                current_user = reddit.user.me()
                console.print(f"  [green]✓[/green] u/{user.reddit_username} (verified)")
            except Exception:
                console.print(f"  [red]✗[/red] u/{user.reddit_username} (token expired)")


@app.command()
def logout(
    username: str = typer.Argument(
        ..., help="Reddit username to log out (without u/)"
    ),
) -> None:
    """Remove stored credentials for a user."""
    with get_session() as session:
        user = session.query(User).filter(User.reddit_username == username).first()

        if not user:
            console.print(f"[yellow]User u/{username} not found.[/yellow]")
            raise typer.Exit(1)

        session.delete(user)
        console.print(f"[green]Logged out u/{username}[/green]")
