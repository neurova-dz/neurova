"""Flask application factory."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, g, redirect, render_template, request, url_for
from flask_login import current_user

from app.config import Config
from app.extensions import celery, csrf, db, limiter, login_manager, mail, migrate


# ---------------------------------------------------------------------------
# Celery integration
# ---------------------------------------------------------------------------

def make_celery(app: Flask):
    celery.conf.update(
        broker_url=app.config["CELERY_BROKER_URL"],
        result_backend=app.config["CELERY_RESULT_BACKEND"],
        BRAIN_MODEL_PATH=app.config["BRAIN_MODEL_PATH"],
        RETINA_MODEL_PATH=app.config["RETINA_MODEL_PATH"],
        RETINA_THRESHOLDS_PATH=app.config["RETINA_THRESHOLDS_PATH"],
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_soft_time_limit=app.config.get("CELERY_TASK_SOFT_TIME_LIMIT", 55 * 60),
        task_time_limit=app.config.get("CELERY_TASK_TIME_LIMIT", 60 * 60),
    )

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask

    from celery.signals import task_failure

    from app.models.medical import InferenceJob

    @task_failure.connect
    def _inference_task_failure(sender=None, task_id=None, exception=None, args=None, **_kwargs):
        if not sender or getattr(sender, "name", None) != "run_inference_job":
            return
        if not args:
            return
        job_id = args[0]
        with app.app_context():
            job = InferenceJob.query.get(job_id)
            if not job:
                return
            st = getattr(job.status, "value", job.status)
            if str(st) in ("done", "failed", "timed_out", "cancelled"):
                return
            job.status = "failed"
            job.error_message = str(exception) if exception else "task_failure"
            job.error_code = job.error_code or "unknown"
            job.progress = 100
            job.finished_at = datetime.utcnow()
            db.session.commit()

    import app.tasks.inference_tasks  # noqa: F401 - register Celery tasks

    return celery


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _configure_logging(app: Flask) -> None:
    level = logging.DEBUG if app.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )


def _configure_sentry(app: Flask) -> None:
    dsn = app.config.get("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration

        sentry_sdk.init(
            dsn=dsn,
            integrations=[FlaskIntegration()],
            traces_sample_rate=0.0,
            environment=app.config.get("NEUROVA_ENV", "development"),
        )
    except Exception:  # noqa: BLE001
        app.logger.warning("Sentry SDK not installed; skipping init.")


def create_app(config_class=Config):
    base_dir = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates"),
    )
    app.config.from_object(config_class)
    if not app.config.get("TESTING") and not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and set DATABASE_URL, "
            "or export DATABASE_URL in your environment."
        )
    _configure_logging(app)
    _configure_sentry(app)

    # storage folders
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["RESULTS_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["EXPORT_FOLDER"]).mkdir(parents=True, exist_ok=True)

    # extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    csrf.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)

    # Talisman applies security headers (HSTS, secure cookies, CSP). It's only
    # enabled when not in testing mode to keep tests simple.
    if not app.config.get("TESTING"):
        try:
            from flask_talisman import Talisman

            csp = {
                "default-src": ["'self'"],
                "img-src": ["'self'", "data:", "blob:"],
                "style-src": [
                    "'self'", "'unsafe-inline'",
                    "https://cdn.jsdelivr.net", "https://fonts.googleapis.com",
                ],
                "script-src": [
                    "'self'", "'unsafe-inline'",
                    "https://cdn.jsdelivr.net", "https://unpkg.com",
                ],
                "font-src": ["'self'", "https://fonts.gstatic.com", "data:"],
                "connect-src": ["'self'"],
                "frame-src": ["'self'", "blob:"],
            }
            Talisman(
                app,
                content_security_policy=csp,
                content_security_policy_nonce_in=[],
                force_https=app.config.get("PREFERRED_URL_SCHEME") == "https",
                strict_transport_security=app.config.get("PREFERRED_URL_SCHEME") == "https",
                session_cookie_secure=app.config.get("SESSION_COOKIE_SECURE", False),
                frame_options="SAMEORIGIN",
            )
        except Exception:  # noqa: BLE001
            app.logger.info("flask-talisman not installed; skipping security headers.")

    # Import models so SQLAlchemy/Alembic see them.
    from app.models import (  # noqa: F401
        AuditLog,
        Clinic,
        Doctor,
        Exam,
        FolderShare,
        InferenceJob,
        InferenceResult,
        Invitation,
        MedicalFolder,
        Notification,
        PasswordResetToken,
        Patient,
        User,
    )

    # CLI
    from app.cli import register_cli
    register_cli(app)

    # Blueprints
    from app.routes.admin import admin_bp
    from app.routes.auth import auth_bp
    from app.routes.clinic import clinic_bp
    from app.routes.doctor import doctor_bp
    from app.routes.exams import exams_bp
    from app.routes.notifications import notifications_bp
    from app.routes.patients import patients_bp
    from app.routes.results import results_bp
    from app.routes.site import site_bp
    from app.urls import build_nv_site_url, register_url_helpers

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(clinic_bp)
    app.register_blueprint(doctor_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(exams_bp)
    app.register_blueprint(results_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(site_bp)
    register_url_helpers(app)
    app.jinja_env.globals["nv_site"] = build_nv_site_url

    # ----- request context -----

    @app.before_request
    def _attach_request_id():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]

    @app.context_processor
    def inject_globals():
        from app.services.navigation import nav_items_for, role_label
        from app.services.notifications_service import unread_notifications_count
        from app.specialty import normalize_doctor_specialty

        wf = None
        unread = 0
        nav_items = []
        if current_user.is_authenticated:
            wf = normalize_doctor_specialty(getattr(current_user, "specialty", None))
            nav_items = nav_items_for(current_user)
            try:
                unread = unread_notifications_count(current_user)
            except Exception:  # noqa: BLE001
                unread = 0
        return dict(
            doctor_workflow=wf,
            nv_site=build_nv_site_url,
            nv_nav_items=nav_items,
            nv_role_label=(role_label(current_user) if current_user.is_authenticated else None),
            nv_unread_count=unread,
        )

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            if current_user.is_superadmin:
                return redirect(url_for("admin.overview"))
            if current_user.is_clinic_admin:
                return redirect(url_for("clinic.overview"))
            return redirect(url_for("doctor.dashboard"))
        return redirect(url_for("site.landing"))

    # ----- health -----

    @app.route("/healthz")
    def healthz():
        return {"status": "ok", "ts": datetime.utcnow().isoformat() + "Z"}

    @app.route("/readyz")
    def readyz():
        from app.services.worker_health import ping_db, ping_redis
        db_state = ping_db()
        redis_state = ping_redis()
        ok = db_state.get("ok") and redis_state.get("ok")
        return ({"status": "ready" if ok else "degraded",
                 "db": db_state, "redis": redis_state},
                200 if ok else 503)

    # ----- error handlers -----

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(_error):
        return render_template("errors/500.html"), 500

    @app.errorhandler(429)
    def rate_limited(_error):
        return render_template("errors/429.html"), 429

    # CSRF errors
    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return render_template("errors/403.html", reason=str(error.description)), 400

    make_celery(app)
    return app
