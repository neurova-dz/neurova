"""Best-effort email sending. Silently no-ops when ``NEUROVA_ENABLE_EMAIL`` is false.

Templates render Jinja first; recipients see plain text only when HTML is omitted.
When email is disabled or sending fails, :func:`flash_invitation_delivery`
surfaces the invite URL in the UI so demo/dev flows still work without SMTP.
"""

from __future__ import annotations

import logging
from typing import Iterable

from flask import current_app, flash, render_template
from flask_mail import Message
from markupsafe import Markup, escape

from app.extensions import mail


logger = logging.getLogger(__name__)


def flash_invitation_delivery(
    *,
    email: str,
    invite_url: str,
    mail_sent: bool,
    lead_when_no_mail: str | None = None,
) -> None:
    """Flash outcome of sending an invitation: email-only if sent, else a clickable demo link."""

    if mail_sent:
        flash(f"Invitation email sent to {email}.", "success")
        return

    lead = lead_when_no_mail or (
        "Demo: Email off — Share this invite link so they can set a password and sign in:"
    )
    safe_email = escape(email)
    safe_url = escape(invite_url)
    body = Markup(
        f'<p class="nv-flash-invite__lead mb-2"><strong>{escape(lead)}</strong> '
        f'<span class="nv-muted">({safe_email})</span></p>'
        f'<p class="nv-flash-invite__url mb-0"><a class="nv-alert-link" href="{safe_url}"><code>{safe_url}</code></a></p>'
    )
    flash(body, "info")


def send_email(
    *,
    subject: str,
    recipients: Iterable[str],
    template: str,
    context: dict | None = None,
) -> bool:
    """Render ``templates/email/<template>.html`` (and ``.txt`` if present) and send.

    Returns True on success, False on failure. Failures are logged but never raised.
    """

    if not current_app.config.get("NEUROVA_ENABLE_EMAIL"):
        logger.info("email disabled — skipped %s to %s", subject, list(recipients))
        return False

    ctx = context or {}
    body_text = render_template(f"email/{template}.txt", **ctx)
    try:
        body_html = render_template(f"email/{template}.html", **ctx)
    except Exception:  # noqa: BLE001 - HTML template is optional
        body_html = None

    msg = Message(
        subject=subject,
        recipients=list(recipients),
        body=body_text,
        html=body_html,
    )
    try:
        mail.send(msg)
        return True
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send email %s to %s", subject, list(recipients))
        return False
