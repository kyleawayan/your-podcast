"""Content analyzer using Claude API to identify high-value posts."""

import re

from anthropic import Anthropic

from your_podcast.db.models import Post
from your_podcast.settings import get_settings


def analyze_post_value(post: Post) -> dict:
    """
    Analyze a Reddit post to determine if it's worth deep-diving.

    Uses Claude to evaluate:
    - How interesting/engaging the content is
    - Controversy level
    - Discussion potential
    - Whether full article/link content would add value

    Args:
        post: Reddit post to analyze

    Returns:
        dict with:
        - score: 0-10 rating of content value
        - should_fetch_url: bool indicating if we should fetch full URL content
        - reasoning: explanation of the score
    """
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)

    prompt = f"""Analyze this Reddit post to determine if it's worth deep-diving in a podcast episode.

Post Title: {post.title}
Subreddit: r/{post.subreddit}
URL: {post.url}
Content: {post.content or 'No text content (link post)'}

Rate this post 0-10 for podcast "juiciness" based on:
1. Is the title intriguing, controversial, or discussion-worthy?
2. Would listeners find this interesting or entertaining?
3. Is there a story, drama, hot take, or useful insight here?
4. Should we fetch the full URL content? (yes if it's an article/blog, no if image/video/reddit-only)

Be generous with scores - anything mildly interesting should be 5+. Only score 0-2 for truly boring posts.

Respond in this exact format:
SCORE: [0-10]
FETCH_URL: [yes/no]
REASONING: [1-2 sentence explanation]"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0].text

        # Parse response
        lines = content.strip().split("\n")
        score = 5  # Default to 5 if parsing fails
        should_fetch = False
        reasoning = ""

        for line in lines:
            line_upper = line.upper()
            if line_upper.startswith("SCORE:"):
                # Extract just the number, handling formats like "7", "7/10", etc.
                score_str = line.split(":", 1)[1].strip()
                match = re.search(r"\d+", score_str)
                if match:
                    score = min(10, int(match.group()))
            elif line_upper.startswith("FETCH_URL:"):
                should_fetch = "yes" in line.lower()
            elif line_upper.startswith("REASONING:"):
                reasoning = line.split(":", 1)[1].strip()

        return {
            "score": score,
            "should_fetch_url": should_fetch,
            "reasoning": reasoning,
        }

    except Exception:
        # Fallback - default to score 5 since RSS doesn't have engagement metrics
        return {
            "score": 5,
            "should_fetch_url": False,
            "reasoning": "API error. Using default score.",
        }


def filter_and_score_posts(posts: list[Post], min_score: int = 5) -> list[tuple[Post, dict]]:
    """
    Analyze multiple posts and return those worth including.

    Args:
        posts: List of Reddit posts to analyze
        min_score: Minimum score threshold (0-10)

    Returns:
        List of (post, analysis) tuples sorted by score descending
    """
    scored_posts = []

    for post in posts:
        analysis = analyze_post_value(post)
        if analysis["score"] >= min_score:
            scored_posts.append((post, analysis))

    # Sort by score descending
    scored_posts.sort(key=lambda x: x[1]["score"], reverse=True)

    return scored_posts
