"""Application configuration.

All values come from environment variables (``.env`` is loaded from the project root).
Production deployments should override at minimum:
``SECRET_KEY``, ``DATABASE_URL``, ``CELERY_BROKER_URL``, ``CELERY_RESULT_BACKEND``.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class Config:
    BASE_DIR = Path(__file__).resolve().parent.parent

    # --- Flask core ---
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    PREFERRED_URL_SCHEME = os.getenv("PREFERRED_URL_SCHEME", "http")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool(os.getenv("SESSION_COOKIE_SECURE"), False)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.getenv("SESSION_HOURS", "12")))
    WTF_CSRF_TIME_LIMIT = int(os.getenv("WTF_CSRF_TIME_LIMIT", str(60 * 60 * 4)))

    # --- Database ---
    # Requires DATABASE_URL in the environment or project-root .env.
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # --- File storage ---
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str(BASE_DIR / "storage" / "uploads"))
    RESULTS_FOLDER = os.getenv("RESULTS_FOLDER", str(BASE_DIR / "storage" / "results"))
    EXPORT_FOLDER = os.getenv("EXPORT_FOLDER", str(BASE_DIR / "storage" / "exports"))

    # --- Inference models ---
    BRAIN_MODEL_PATH = os.getenv(
        "BRAIN_MODEL_PATH",
        str(BASE_DIR / "storage" / "models" / "brain" / "model_phase_1.keras"),
    )
    RETINA_MODEL_PATH = os.getenv(
        "RETINA_MODEL_PATH",
        str(BASE_DIR / "storage" / "models" / "retina" / "best_pytorch_h100_aptos.pth"),
    )
    RETINA_THRESHOLDS_PATH = os.getenv(
        "RETINA_THRESHOLDS_PATH",
        str(BASE_DIR / "storage" / "models" / "retina" / "best_thresholds.csv"),
    )

    # --- Celery ---
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
    MAX_CONTENT_LENGTH = 1_000 * 1024 * 1024  # 1 GB upload ceiling

    INFERENCE_JOB_STALE_MINUTES = int(os.getenv("INFERENCE_JOB_STALE_MINUTES", "45"))
    CELERY_TASK_SOFT_TIME_LIMIT = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", str(55 * 60)))
    CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", str(60 * 60)))
    INFERENCE_MAX_RETRIES = int(os.getenv("INFERENCE_MAX_RETRIES", "2"))

    # --- Email (optional) ---
    NEUROVA_ENABLE_EMAIL = _bool(os.getenv("NEUROVA_ENABLE_EMAIL"), False)
    MAIL_SERVER = os.getenv("MAIL_SERVER", "localhost")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "25"))
    MAIL_USE_TLS = _bool(os.getenv("MAIL_USE_TLS"), False)
    MAIL_USE_SSL = _bool(os.getenv("MAIL_USE_SSL"), False)
    MAIL_USERNAME = os.getenv("MAIL_USERNAME") or None
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD") or None
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "no-reply@neurova.dev")

    # --- Auth security ---
    INVITE_TTL_HOURS = int(os.getenv("INVITE_TTL_HOURS", "72"))
    PASSWORD_RESET_TTL_MINUTES = int(os.getenv("PASSWORD_RESET_TTL_MINUTES", "30"))
    RATELIMIT_DEFAULT_AUTH = os.getenv("RATELIMIT_DEFAULT_AUTH", "20 per minute")

    # --- Feature flags ---
    FEATURE_SUPERADMIN = _bool(os.getenv("FEATURE_SUPERADMIN"), True)
    FEATURE_CLINIC_BOARD = _bool(os.getenv("FEATURE_CLINIC_BOARD"), True)
    FEATURE_NOTIFICATIONS = _bool(os.getenv("FEATURE_NOTIFICATIONS"), True)
    FEATURE_PDF_REPORT = _bool(os.getenv("FEATURE_PDF_REPORT"), True)
    FEATURE_RGPD_EXPORT = _bool(os.getenv("FEATURE_RGPD_EXPORT"), True)

    # --- Observability ---
    SENTRY_DSN = os.getenv("SENTRY_DSN") or None
    NEUROVA_ENV = os.getenv("NEUROVA_ENV", "development")
    # Quick-login tiles on /auth/login (seeded neurova.dev accounts). Off by default in production.
    SHOW_DEMO_LOGIN = _bool(
        os.getenv("NEUROVA_SHOW_DEMO_LOGIN"),
        NEUROVA_ENV != "production",
    )


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    NEUROVA_ENABLE_EMAIL = False
    SECRET_KEY = "test-secret"
    SHOW_DEMO_LOGIN = False
