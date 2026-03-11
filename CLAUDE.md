# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

FastAPI REST backend for SnippetsCLI (and a React web frontend) — a note-taking system with sources, authors, tags, and publishers. Uses PostgreSQL via psycopg2 (synchronous, raw SQL). Multi-user with JWT auth and invite-code-gated registration.

## Commands

```bash
# Dev (Docker, uses .env.dev) — no HTTPS
docker compose up --build

# Prod (Docker + Caddy HTTPS) — edit Caddyfile with your domain first
ENV=prod docker compose up --build

# Without Docker
pip install -r requirements.txt
uvicorn main:app --reload

# Health check
curl http://localhost:8000/health
```

No test suite exists yet. No linter is configured.

## Architecture

Three-file backend with no ORM:

- **main.py** — FastAPI app: all routes, Pydantic request models, JWT middleware, lifespan (DB init/teardown). Routes call `db.*` functions and convert results via `to_dict`/`to_list` helpers that serialize datetimes. Swagger UI (`/docs`, `/redoc`) only enabled when `DEBUG=true`.
- **db.py** — Data access layer: every function takes a `conn` (psycopg2 connection with `RealDictCursor`) as its first arg, runs raw SQL, and returns dicts. Most queries filter by `user_id` for multi-tenancy. `init_db()` creates a `ThreadedConnectionPool`, runs `schema.sql`, and cleans up old login attempts (>30 days).
- **auth.py** — JWT helpers (PyJWT + bcrypt). `JWT_SECRET` and `JWT_EXPIRY_HOURS` from env vars (default expiry: 720h / 30 days). Tokens carry `user_id`, `username`, and `jti` (UUID for token revocation).
- **schema.sql** — DDL with `IF NOT EXISTS` for idempotent startup. Includes seed data for `source_types` and versioned migration blocks. Schema version tracked in `schema_version` table (currently **v7**).
- **Caddyfile** — Caddy reverse proxy for `backend.snippets.eu` with automatic HTTPS.
- **Dockerfile** — Python 3.12-slim, runs as non-root `appuser`, 4 uvicorn workers.
- **docker-compose.yml** — Backend + Caddy services. No database container (uses external PostgreSQL). Backend port 8000 bound to `127.0.0.1` only.

## Key Patterns

- **Auth flow**: JWT middleware in `main.py` checks `Authorization: Bearer <token>` on all paths except `/health`, `/register`, `/login`. Authenticated user ID is stored on `request.state.user_id`. Tokens include a `jti` claim; `POST /logout` revokes the current token by storing its `jti` in the `revoked_tokens` table. The middleware checks this table on every authenticated request.
- **Invite-code registration**: `POST /register` requires a valid `invite_code`. Codes are single-use, created by the invite admin (`INVITE_ADMIN` env var, defaults to `"adam"`). Endpoints: `POST /invite-codes` (create), `GET /invite-codes` (list) — both admin-only.
- **Brute-force protection**: Failed login/change-password attempts are tracked in `login_attempts`. After 5 failures within 15 minutes (`MAX_LOGIN_ATTEMPTS`, `LOCKOUT_MINUTES` in `db.py`), further attempts are rejected with HTTP 429. Attempts older than 30 days are cleaned on startup.
- **CORS**: Configured with `allow_credentials=True` for browser-based React frontend. Origins set via `ALLOWED_ORIGINS` env var (comma-separated).
- **HTTPS**: Production uses Caddy as a reverse proxy (in `docker-compose.yml`). Caddy auto-provisions TLS certs via Let's Encrypt. Port 8000 is bound to `127.0.0.1` so only Caddy can reach the backend.
- **Multi-tenancy**: Most tables have a `user_id` column. Almost every `db.*` function filters by `user_id`. Exception: `source_types` are shared across all users.
- **Connection pooling**: `ThreadedConnectionPool` stored on `app.state.pool` (min/max size via `DB_POOL_MIN`/`DB_POOL_MAX` env vars, defaults 2/10). The request middleware checks out a connection per request (`request.state.conn`) and returns it after the response. Each `db.*` function calls `conn.commit()` after writes. Uvicorn runs 4 workers (each with its own pool).
- **Env file selection**: `main.py` loads `.env.{APP_ENV}` (defaults to `.env.dev`). Docker compose sets this via the `ENV` variable.
- **Schema migrations**: Done inline in `schema.sql` with idempotent `DO $$ ... END $$` blocks guarded by `schema_version` checks. Current version: **7**. Migrations: v2 (user_id columns), v3 (NOT NULL + CASCADE), v4 (revoked_tokens), v5 (login_attempts), v6 (invite_codes), v7 (notes.updated_at).
- **Citation builder**: `db.build_citation()` generates MLA-style citation strings from source, authors, publisher, and metadata.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://localhost/snippets` | PostgreSQL connection string |
| `JWT_SECRET` | `change-me-in-production` | Secret for signing JWTs |
| `JWT_EXPIRY_HOURS` | `720` | Token lifetime (30 days) |
| `ALLOWED_ORIGINS` | (empty) | Comma-separated CORS origins |
| `DEBUG` | `false` | Enables `/docs` and `/redoc` when `true` |
| `DB_POOL_MIN` | `2` | Min connections per worker pool |
| `DB_POOL_MAX` | `10` | Max connections per worker pool |
| `APP_ENV` | `dev` | Selects `.env.{APP_ENV}` file |
| `INVITE_ADMIN` | `adam` | Username allowed to create/view invite codes |

## Database Schema

Core tables: `users`, `notes`, `sources`, `source_types`, `source_authors`, `source_publishers`, `tags`, `note_tags`, `revoked_tokens`, `login_attempts`, `invite_codes`, `schema_version`.

- **notes** optionally link to a source; have `locator_type`/`locator_value` fields and an `updated_at` timestamp.
- **sources** have authors (ordered via `author_order`), a type, a publisher, and metadata fields (year, url, accessed_date, edition, pages, extra_notes).
- **tags** are per-user, stored lowercase, linked to notes via `note_tags` junction table.
- **invite_codes** are single-use; track `created_by`, `used_by`, and timestamps.
- **login_attempts** track failed logins by username with timestamps for rate limiting.
- **revoked_tokens** stores `jti` values of logged-out JWT tokens.
- **source_types** are shared across all users (seeded: Book, Article, Magazine, YouTube Video, Other).

## API Routes

Public: `GET /health`, `POST /register`, `POST /login`. All others require JWT.

- **Auth**: `/register`, `/login`, `/logout`, `/change-password`, `/me`
- **Invite codes** (admin-only): `POST /invite-codes`, `GET /invite-codes`
- **Notes**: CRUD + search, bulk source assignment, tag management
- **Sources**: CRUD + search, recent, citation, author management
- **Source types**: list, create, get (shared across users)
- **Publishers**: search, city search, get-or-create
- **Authors**: list, recent, search, name autocomplete (last-names, first-names)
- **Tags**: list, recent, search, by-name lookup, get-or-create

## Deployment

Hosted on Scaleway. Domain: `backend.snippets.eu`. DNS via Cloudflare (DNS-only mode). See `DEPLOY.md` for full instructions.
