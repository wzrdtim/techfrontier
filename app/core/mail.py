from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def send_email(
    *,
    to: str,
    subject: str,
    body: str,
    reply_to: str | None = None,
) -> bool:
    """Send a plain-text email via SMTP. Returns False if SMTP is unset or send fails."""
    settings = get_settings()
    if not settings.smtp_host.strip():
        logger.debug("SMTP not configured; skipping email to %s", to)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.mail_from
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        return True
    except OSError:
        logger.exception("Failed to send email to %s", to)
        return False


def notify_admin_of_contact(*, sender_email: str, subject: str, body: str) -> bool:
    settings = get_settings()
    return send_email(
        to=settings.admin_email,
        subject=f"[{settings.app_name}] {subject.strip()}",
        body=(
            f"New contact message on {settings.app_name}\n\n"
            f"From: {sender_email.strip()}\n"
            f"Subject: {subject.strip()}\n\n"
            f"{body.strip()}\n"
        ),
        reply_to=sender_email.strip(),
    )
