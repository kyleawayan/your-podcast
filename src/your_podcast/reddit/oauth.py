"""Reddit OAuth Code Flow implementation."""

import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import praw

from your_podcast.settings import get_settings


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback."""

    def log_message(self, format: str, *args) -> None:
        """Suppress default logging."""
        pass

    def do_GET(self) -> None:
        """Handle the OAuth callback GET request."""
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return

        query = parse_qs(parsed.query)

        # Check for errors
        if "error" in query:
            self.server.oauth_error = query["error"][0]  # type: ignore
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Authorization Failed</h1><p>You can close this window.</p>")
            return

        # Verify state
        if query.get("state", [None])[0] != self.server.expected_state:  # type: ignore
            self.server.oauth_error = "state_mismatch"  # type: ignore
            self.send_error(400, "State mismatch")
            return

        # Get the authorization code
        self.server.auth_code = query.get("code", [None])[0]  # type: ignore
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<h1>Authorization Successful!</h1>"
            b"<p>You can close this window and return to the terminal.</p>"
        )


class OAuthServer(HTTPServer):
    """HTTP server that stores OAuth state."""

    auth_code: str | None = None
    oauth_error: str | None = None
    expected_state: str = ""


def start_oauth_flow() -> tuple[str, str]:
    """Start the OAuth flow and return (refresh_token, username).

    This will:
    1. Start a local HTTP server for the callback
    2. Open the browser to Reddit's authorization page
    3. Wait for the callback with the authorization code
    4. Exchange the code for a refresh token
    5. Return the refresh token and username

    Returns:
        Tuple of (refresh_token, reddit_username)

    Raises:
        RuntimeError: If authorization fails
    """
    settings = get_settings()

    # Create PRAW instance for OAuth
    reddit = praw.Reddit(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret or None,
        redirect_uri=settings.reddit_redirect_uri,
        user_agent=settings.reddit_user_agent,
    )

    # Generate a random state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Get the authorization URL
    scopes = ["identity", "mysubreddits", "read"]
    auth_url = reddit.auth.url(scopes=scopes, state=state, duration="permanent")

    # Start the callback server
    server = OAuthServer(("localhost", 8080), OAuthCallbackHandler)
    server.expected_state = state

    # Open the browser
    print(f"Opening browser for Reddit authorization...")
    print(f"If the browser doesn't open, visit: {auth_url}")
    webbrowser.open(auth_url)

    # Wait for the callback (single request)
    print("Waiting for authorization...")
    server.handle_request()

    # Check for errors
    if server.oauth_error:
        raise RuntimeError(f"Authorization failed: {server.oauth_error}")

    if not server.auth_code:
        raise RuntimeError("No authorization code received")

    # Exchange the code for a refresh token
    refresh_token = reddit.auth.authorize(server.auth_code)

    # Get the username
    username = reddit.user.me().name  # type: ignore

    return refresh_token, username


def get_reddit_client(refresh_token: str) -> praw.Reddit:
    """Create a PRAW Reddit instance using a refresh token.

    Args:
        refresh_token: The user's Reddit refresh token

    Returns:
        Authenticated PRAW Reddit instance
    """
    settings = get_settings()

    return praw.Reddit(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret or None,
        refresh_token=refresh_token,
        user_agent=settings.reddit_user_agent,
    )
