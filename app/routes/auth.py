"""Authentication, clinic onboarding and invite acceptance."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from app.demo_accounts import DEMO_LOGIN_ACCOUNTS
from app.extensions import db, limiter
from app.forms.auth import (
    AcceptInviteForm,
    ClinicRegisterForm,
    ForgotForm,
    LoginForm,
    ResetForm,
)
from app.models.clinic import Clinic
from app.models.doctor import Doctor
from app.models.invitation import Invitation, PasswordResetToken
from app.models.user import User
from app.services.audit_service import log_event
from app.services.mailer import send_email


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ---- helpers --------------------------------------------------------------


def _redirect_after_login(user: User, fallback_next: str | None = None) -> str:
    """Return the path to redirect a freshly authenticated user to."""

    next_url = (request.args.get("next") or fallback_next or "").strip()
    if next_url:
        # Only allow internal redirects.
        parsed = urlparse(next_url)
        if not parsed.netloc and not parsed.scheme:
            return next_url

    if user.is_superadmin:
        return url_for("admin.overview")
    if user.is_clinic_admin:
        return url_for("clinic.overview")
    return url_for("doctor.dashboard")


def _slugify(value: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return s[:80] or "clinic"


def _ensure_unique_slug(base: str) -> str:
    slug = base
    suffix = 1
    while Clinic.query.filter_by(slug=slug).first() is not None:
        suffix += 1
        slug = f"{base}-{suffix}"
    return slug


# ---- login / logout -------------------------------------------------------


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config.get("RATELIMIT_DEFAULT_AUTH", "20 per minute"),
               methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(_redirect_after_login(current_user))

    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(form.password.data) and user.is_active_account:
            login_user(user, remember=bool(form.remember.data))
            user.last_login_at = datetime.utcnow()
            db.session.commit()
            log_event("auth.login", "user", user.id, {"role": user.role_value})
            return redirect(_redirect_after_login(user))
        flash("Invalid email or password.", "danger")
        log_event("auth.login_failed", "user", None, {"email": email})

    show_demo = bool(current_app.config.get("SHOW_DEMO_LOGIN"))
    demo_accounts = DEMO_LOGIN_ACCOUNTS if show_demo else ()
    return render_template("auth/login.html", form=form, demo_login_accounts=demo_accounts)


@auth_bp.route("/logout")
@login_required
def logout():
    log_event("auth.logout", "user", current_user.id)
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))


# ---- clinic registration --------------------------------------------------


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Legacy URL → clinic-first registration."""
    return redirect(url_for("auth.register_clinic"))


@auth_bp.route("/register-clinic", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def register_clinic():
    if current_user.is_authenticated:
        return redirect(_redirect_after_login(current_user))

    form = ClinicRegisterForm()
    if form.validate_on_submit():
        admin_email = form.admin_email.data.strip().lower()
        if User.query.filter_by(email=admin_email).first():
            flash("An account already exists with that email.", "warning")
            return render_template("auth/register_clinic.html", form=form)

        clinic = Clinic(
            name=form.clinic_name.data.strip(),
            slug=_ensure_unique_slug(_slugify(form.clinic_name.data)),
            country=form.clinic_country.data or None,
            phone=form.clinic_phone.data or None,
            address=form.clinic_address.data or None,
            email=(form.contact_email.data or admin_email).strip().lower() or None,
            plan="trial",
            is_active=True,
        )
        db.session.add(clinic)
        db.session.flush()

        admin = User(
            email=admin_email,
            full_name=form.admin_full_name.data.strip(),
            role="clinic_admin",
            clinic_id=clinic.id,
            is_active_account=True,
        )
        admin.set_password(form.admin_password.data)
        db.session.add(admin)
        db.session.flush()

        clinic.created_by_user_id = admin.id

        # Optional: create a Doctor profile for the admin so they can also work clinically.
        # We default to no specialty; admin can pick one in settings.
        db.session.add(
            Doctor(
                user_id=admin.id,
                clinic_id=clinic.id,
                specialty=None,
                preferences_json={"default_modality": "", "compact_results": False},
            )
        )
        db.session.commit()

        log_event(
            "clinic.create",
            "clinic",
            clinic.id,
            {"name": clinic.name, "admin_email": admin.email},
            actor_user_id=admin.id,
            clinic_id=clinic.id,
        )

        login_user(admin)
        admin.last_login_at = datetime.utcnow()
        db.session.commit()
        flash(f"Welcome to NEUROVA, {admin.full_name}.", "success")
        return redirect(url_for("clinic.overview"))

    return render_template("auth/register_clinic.html", form=form)


# ---- invitation acceptance -------------------------------------------------


@auth_bp.route("/accept-invite/<token>", methods=["GET", "POST"])
def accept_invite(token: str):
    invitation = Invitation.find_active_by_token(token)
    if not invitation:
        flash("This invitation link is invalid or has expired.", "danger")
        return redirect(url_for("auth.login"))

    form = AcceptInviteForm()
    if request.method == "GET":
        form.full_name.data = invitation.full_name or ""

    if form.validate_on_submit():
        existing = User.query.filter_by(email=invitation.email).first()
        if existing:
            existing.is_active_account = True
            existing.set_password(form.password.data)
            existing.full_name = form.full_name.data.strip()
            user = existing
        else:
            user = User(
                email=invitation.email,
                full_name=form.full_name.data.strip(),
                role=invitation.role,
                clinic_id=invitation.clinic_id,
                is_active_account=True,
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.flush()

        if invitation.role == "doctor" and not user.doctor_profile:
            db.session.add(
                Doctor(
                    user_id=user.id,
                    clinic_id=invitation.clinic_id,
                    specialty=invitation.specialty,
                    preferences_json={"default_modality": "", "compact_results": False},
                )
            )
        elif invitation.role == "clinic_admin" and not user.doctor_profile:
            db.session.add(
                Doctor(
                    user_id=user.id,
                    clinic_id=invitation.clinic_id,
                    specialty=invitation.specialty,
                    preferences_json={"default_modality": "", "compact_results": False},
                )
            )

        invitation.accepted_at = datetime.utcnow()
        db.session.commit()

        log_event(
            "auth.invite_accepted",
            "user",
            user.id,
            {"role": user.role_value},
            actor_user_id=user.id,
            clinic_id=user.clinic_id,
        )
        login_user(user)
        user.last_login_at = datetime.utcnow()
        db.session.commit()
        flash("Welcome aboard. Your account is ready.", "success")
        return redirect(_redirect_after_login(user))

    return render_template("auth/accept_invite.html", form=form, invitation=invitation)


# ---- password reset --------------------------------------------------------


@auth_bp.route("/forgot", methods=["GET", "POST"])
@limiter.limit("8 per hour", methods=["POST"])
def forgot():
    form = ForgotForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and user.is_active_account:
            ttl = current_app.config.get("PASSWORD_RESET_TTL_MINUTES", 30)
            row, raw_token = PasswordResetToken.issue(user.id, ttl_minutes=ttl)
            db.session.add(row)
            db.session.commit()
            reset_url = url_for("auth.reset", token=raw_token, _external=True)
            send_email(
                subject="Reset your NEUROVA password",
                recipients=[user.email],
                template="password_reset",
                context={"user": user, "reset_url": reset_url, "ttl_minutes": ttl},
            )
            log_event(
                "auth.password_reset_requested",
                "user",
                user.id,
                actor_user_id=user.id,
                clinic_id=user.clinic_id,
            )
        # Always show the same message to avoid disclosing valid emails.
        flash("If an account exists for that email, a reset link is on its way.", "info")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot.html", form=form)


@auth_bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token: str):
    row = PasswordResetToken.find_active_by_token(token)
    if not row:
        flash("This reset link is invalid or has expired.", "danger")
        return redirect(url_for("auth.forgot"))

    form = ResetForm()
    if form.validate_on_submit():
        user = row.user
        user.set_password(form.password.data)
        row.used_at = datetime.utcnow()
        db.session.commit()
        log_event(
            "auth.password_reset",
            "user",
            user.id,
            actor_user_id=user.id,
            clinic_id=user.clinic_id,
        )
        flash("Your password has been updated. Please sign in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset.html", form=form, token=token)
