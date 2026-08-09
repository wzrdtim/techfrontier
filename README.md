# Techfrontier

A personal blog built with **FastAPI**, **PostgreSQL**, **Tailwind CSS**, and server-rendered **HTML/JavaScript**.

## Features

- Public blog pages styled with Tailwind
- Admin panel to create, edit, update, and delete posts
- JWT auth for admin only (API bearer + admin HTTP-only cookie)
- Alembic migrations for Postgres
- Pytest coverage for auth, posts, and admin flows

## Project structure

```
app/                  FastAPI application
admin/                Admin templates
frontend/             Public templates and static assets
migrations/           Alembic migrations
tests/                Pytest suite
```

## Prerequisites

- Python 3.9+
- Node.js 18+ (Tailwind build)
- PostgreSQL 14+

## Setup

1. Copy environment config:

```bash
cp .env.example .env
```

2. Create the database:

```bash
createdb blog
```

3. Start everything with:

```bash
./run.sh
```

This creates `.venv` if needed, installs Python + npm deps, builds Tailwind, runs migrations, seeds the admin user, and starts Uvicorn (with CSS watch in reload mode).

Optional overrides:

```bash
PORT=8080 HOST=0.0.0.0 RELOAD=0 RUN_MIGRATIONS=0 BUILD_CSS=0 ./run.sh
```

Open:

- Site: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- Admin: [http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin)
- API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

Default admin (change in `.env`):

- Username: `admin`
- Password: `admin`

## Admin

| Path | Action |
|------|--------|
| `/admin/login` | Admin sign in |
| `/admin` | Post dashboard |
| `/admin/posts/new` | Create post |
| `/admin/posts/{id}/edit` | Edit / update post |
| `/admin/posts/{id}/delete` | Delete post (POST) |

## API overview

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/login` | Admin JWT only |
| GET | `/api/auth/me` | Current admin |
| GET | `/api/posts` | List posts |
| GET | `/api/posts/{slug}` | Get post |
| POST | `/api/posts` | Create post (admin) |
| PATCH | `/api/posts/{id}` | Update post (admin) |
| DELETE | `/api/posts/{id}` | Delete post (admin) |

## Tailwind

Source: `frontend/static/css/input.css`  
Built CSS: `frontend/static/css/main.css`

```bash
npm install
npm run build:css
npm run watch:css
```

## Tests

```bash
source .venv/bin/activate
pytest
```

## Deploy on Render

This repo includes a [Render Blueprint](https://render.com/docs/infrastructure-as-code) at `render.yaml` (free web service in Frankfurt, linked to Postgres `postgres-tf`).

1. Push to GitHub (already at [wzrdtim/techfrontier](https://github.com/wzrdtim/techfrontier)).
2. Open [Dashboard → New → Blueprint](https://dashboard.render.com/select-repo?type=blueprint), or create a Web Service from the repo with the build/start commands in `render.yaml`.
3. Set `ADMIN_PASSWORD` (and confirm `DATABASE_URL` points at your Render Postgres).
4. After deploy, open the `*.onrender.com` URL from the dashboard. Set `SITE_URL` to that HTTPS URL (or your custom domain), then redeploy.
5. Sign in at `/admin` with username `admin` and your password.

Notes:

- Free web services sleep after idle time (first request can be slow).
- Image uploads use **Cloudflare R2** when `R2_*` + `IMAGE_PUBLIC_BASE_URL` are set (recommended: `https://images.techfrontier.se`). Without R2, files fall back to local `frontend/static/uploads/`.
- Optional: set `SMTP_*` in the Render dashboard to email contact form messages to `ADMIN_EMAIL`.

### Cloudflare R2 setup

1. Create an R2 bucket and an API token with Object Read & Write.
2. Attach a custom domain (e.g. `images.techfrontier.se`) to the bucket for public reads.
3. Set the env vars below on Render (and locally in `.env`).
4. New uploads are resized/converted as before, then stored in R2; the DB stores the full CDN URL.

## Environment variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | SQLAlchemy Postgres URL |
| `SECRET_KEY` | JWT signing secret |
| `ALGORITHM` | JWT algorithm (default `HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime |
| `APP_NAME` | Site name shown in templates |
| `DEBUG` | FastAPI debug flag |
| `ADMIN_EMAIL` | Admin account + contact form recipient |
| `ADMIN_USERNAME` | Seeded admin username |
| `ADMIN_PASSWORD` | Seeded admin password |
| `SMTP_HOST` | Optional SMTP host (enables email delivery of contact messages) |
| `SMTP_PORT` | SMTP port (default `587`) |
| `SMTP_USER` / `SMTP_PASSWORD` | SMTP credentials |
| `SMTP_FROM` | From address (defaults to `ADMIN_EMAIL`) |
| `SMTP_USE_TLS` | Use STARTTLS (default `true`) |
| `R2_ACCOUNT_ID` | Cloudflare account ID |
| `R2_ACCESS_KEY_ID` | R2 API access key |
| `R2_SECRET_ACCESS_KEY` | R2 API secret key |
| `R2_BUCKET_NAME` | R2 bucket name |
| `R2_ENDPOINT_URL` | Optional S3 endpoint override |
| `IMAGE_PUBLIC_BASE_URL` | Public CDN base, e.g. `https://images.techfrontier.se` |
