# Your Podcast

A personal project to generate your own personal daily podcasts from Reddit content. Great for listening during commutes.

See the initial plan as of 2026-01-14 at [`docs/reddit-podcast-generator-plan.md`](docs/reddit-podcast-generator-plan.md).

## Quickstart

```bash
# 1. Set the environment variables in .env.example

# 2. Install dependencies
uv sync

# 3. Start the database
docker compose up -d

# 4. Run migrations
uv run alembic upgrade head

# 5. Fetch Reddit subreddits
uv run your-podcast fetch python rust programming

# 6. Generate a podcast (this will take a while)
uv run your-podcast generate

# 7. Generate a longer podcast
uv run your-podcast generate --limit 15 --words 1000
```

## Fetch Options

```bash
# Different sort types
uv run your-podcast fetch python --sort hot          # default
uv run your-podcast fetch python --sort top --time week
uv run your-podcast fetch python --sort controversial --time week
uv run your-podcast fetch python --sort new
```

## Clear Data

```bash
uv run your-podcast clear --posts      # clear posts only
uv run your-podcast clear --episodes   # clear episodes only
uv run your-podcast clear --all        # clear everything
```

## Admin UI

```bash
uv run your-podcast admin
# Visit http://127.0.0.1:8000/admin
```
