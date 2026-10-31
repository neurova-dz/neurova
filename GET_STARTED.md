# Getting started

This guide walks through a **local development** setup on Windows, macOS, or Linux. For containerized MySQL and Redis, you can use **Docker Compose** (see [Docker](#docker-mysql-redis-and-full-stack) below) while still running Flask and Celery on the host, or run the full stack in Compose.

---

## Prerequisites

- **Python 3.12** (matches `Dockerfile` and typical CI)
- **MySQL 8** (local install or Docker)
- **Redis** (local install or Docker)
- Optional: **Docker** + Docker Compose for databases and production-like runs

---

## 1. Clone and virtual environment

```bash
cd hackathon
python -m venv .venv
```

**Windows (PowerShell)**

```powershell
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> Inference dependencies include TensorFlow and PyTorch (CPU wheels from `requirements.txt`). For GPU, install vendor-specific builds and align with your CUDA/driver setup.

---

## 2. Environment variables

Copy the example file and edit values:

```bash
copy .env.example .env
```

On Unix: `cp .env.example .env`

Minimum variables:

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Long random string for sessions and CSRF |
| `DATABASE_URL` | SQLAlchemy URL, e.g. `mysql+pymysql://user:pass@127.0.0.1:3306/hackathon` |
| `CELERY_BROKER_URL` | Usually `redis://localhost:6379/0` |
| `CELERY_RESULT_BACKEND` | Usually `redis://localhost:6379/1` |

Optional:

- `BRAIN_MODEL_PATH`, `RETINA_MODEL_PATH`, `RETINA_THRESHOLDS_PATH` — point to weights under `storage/models/`
- `NEUROVA_ENABLE_EMAIL` — set to `true` when SMTP is configured (`MAIL_*` in `app/config.py`)
- `SENTRY_DSN` — error reporting in non-dev environments

Paths like `UPLOAD_FOLDER`, `RESULTS_FOLDER`, `EXPORT_FOLDER` default under `storage/` if unset.

---

## 3. Create the MySQL database

Create an empty database (UTF-8 / `utf8mb4` recommended), for example:

```sql
CREATE DATABASE hackathon CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Grant your application user appropriate privileges.

---

## 4. Database schema (Alembic)

The team workflow uses **Flask-Migrate**. From the project root:

**Windows (PowerShell)**

```powershell
$env:FLASK_APP = "run.py"
python -m flask db upgrade
```

**macOS / Linux**

```bash
export FLASK_APP=run.py
python -m flask db upgrade
```

Notes:

- **Fresh database**: `flask db upgrade` applies all revisions under `migrations/versions/`.
- **Existing tables** (e.g. created manually from `scripts/init_db.sql`): you may need `flask db stamp head` once so Alembic matches reality—avoid double-applying DDL.
- **`scripts/init_db.sql`** is a full baseline for review and one-off installs; day-to-day use migrations.

Optional seeding / admin CLI (after DB is ready):

```bash
flask superadmin create --email you@example.com --password 'YourSecurePass1!'
flask seed-demo
```

See `app/cli.py` for available commands.

---

## 5. Model and storage directories

Ensure directories exist (the app also creates many of these at startup):

- `storage/uploads` — uploaded exams
- `storage/results` — inference outputs
- `storage/exports` — exports when used
- `storage/models/brain/`, `storage/models/retina/` — place weight files as documented in `.env.example`

These paths should not be committed if they contain large or sensitive data.

---

## 6. Run the Flask application

```bash
python run.py
```

Default development server listens on `http://127.0.0.1:5000` unless configured otherwise.

**Windows note:** `run.py` disables the Werkzeug reloader for stability. After code changes, restart the process so routes and templates reload reliably.

---

## 7. Run the Celery worker

Inference runs in the background. In a **second** terminal (same venv and `.env`):

```bash
celery -A app.extensions.celery worker --loglevel=info
```

Without a running worker, jobs will queue or stall depending on broker configuration.

---

## 8. Verify health

- `GET /healthz` — process alive  
- `GET /readyz` — database and Redis reachability (503 if degraded)

---

## 9. Run tests

```bash
pytest
```

Use `tests/conftest.py` and existing tests for patterns (fixtures, `TESTING` config).

---

## Docker: MySQL, Redis, and full stack

**Services only (DB + Redis)** — start dependencies and point `.env` at `localhost` ports published by Compose.

**Full stack** — `docker-compose.yml` defines `db`, `redis`, `web` (Gunicorn on port 8000), and `worker`. Build and run:

```bash
docker compose up --build
```

Align `DATABASE_URL` in Compose with the `MYSQL_*` variables (see `docker-compose.yml`). The web image uses `gunicorn` and expects migrations to have been applied (run `flask db upgrade` against the same database, or bake a migration step into your deployment pipeline).

---

## Troubleshooting

| Issue | What to check |
|-------|----------------|
| `DATABASE_URL is not set` | `.env` at project root, or export variables before `python run.py` |
| MySQL connection errors | Host, port, user, password, database name; MySQL running |
| Celery tasks not running | Redis up; worker process started; same `CELERY_*` URLs as the app |
| Windows reload / `BuildError` | Restart Flask after route changes (reloader disabled) |
| Heavy ML import errors | CPU vs GPU packages; Python version matches 3.12 |

---

## Next steps

- Read [README.md](README.md) for architecture overview.
- Read [ETAT.md](ETAT.md) for current feature coverage and placeholders.
