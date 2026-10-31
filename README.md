# Neurova — Medical imaging platform

Web application for clinics to manage patient records, imaging exams, asynchronous AI inference, and clinical reporting. Built as a Flask monolith with role-based access, multi-tenant clinics, and a Celery worker for long-running inference jobs.

---

## Capabilities

- **Authentication and roles** — Registration, login, password flows; roles include platform superadmin, clinic administrator, and clinician (doctor).
- **Clinical workflow** — Patients, medical folders with status workflow, exams with modality and model selection, folder sharing where applicable.
- **AI inference** — Background jobs (Celery + Redis) for brain and retina pipelines; results and reporting APIs plus UI views (including 3D brain visualization where implemented).
- **Operations** — Health checks (`/healthz`, `/readyz`), optional Sentry, rate limiting, security headers (Talisman), Docker Compose for MySQL, Redis, web, and worker.

---

## Documentation

| Document | Purpose |
|----------|---------|
| [GET_STARTED.md](GET_STARTED.md) | Environment setup, database migrations, running the app and worker, Docker, tests |

---

## Tech stack

| Layer | Choices |
|-------|---------|
| Application | Python 3.12, Flask, Flask-Login, Flask-WTF, Flask-Migrate, Gunicorn (container) |
| Data | MySQL (SQLAlchemy), Alembic migrations |
| Async jobs | Celery, Redis |
| ML runtime | TensorFlow / PyTorch (CPU wheels by default; GPU optional via environment) |
| Document output | WeasyPrint, Markdown (reports / exports as implemented) |

---

## Repository layout (high level)

```
app/           Application package (routes, models, services, security)
templates/     Jinja2 HTML
migrations/    Alembic revisions
scripts/       SQL baselines and utilities (e.g. init_db.sql)
storage/       Uploads, results, exports, model weights (not committed)
tests/         pytest suite
```

Weight files and large artifacts belong under `storage/` (see `.env.example` for paths).

---

## Quick start

For a full local setup (Python venv, `.env`, MySQL, Redis, migrations, Celery), follow **[GET_STARTED.md](GET_STARTED.md)**.

Minimal sequence:

1. `python -m venv .venv` and activate it; `pip install -r requirements.txt`
2. Copy `.env.example` → `.env` and set `DATABASE_URL`, `SECRET_KEY`, and Celery/Redis URLs
3. `flask db upgrade` (with `FLASK_APP=run.py`)
4. Terminal A: `python run.py` — Terminal B: `celery -A app.extensions.celery worker --loglevel=info`

---

## Contributing

Match existing patterns in `app/` (blueprints under `app/routes/`, services under `app/services/`). After model changes, generate and review Alembic migrations before committing.

