"""Notification email worker job (P16).

send_notification_email: sends one templated email through SMTP with
retries. In dev without SMTP configured it logs the message (the same
fallback email_utils uses for verification codes) -- the job still
"succeeds", because a missing SMTP setup must not spin the retry loop.

The recipient's intent was already checked (preferences) by the
service before enqueueing; this job only delivers.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
import uuid
from email.mime.text import MIMEText
from typing import Any

from app.config import settings

logger = logging.getLogger("sentinelx.worker")

MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5.0

SUBJECT_PREFIX = "[SentinelX]"


async def _deliver(to_email: str, title: str, body: str | None, organization_id: str) -> None:
    """One delivery attempt. Raises on failure so the retry loop sees it."""
    if not settings.smtp_user or not settings.smtp_password:
        logger.info(
            "[SentinelX] SMTP not configured -- notification email for %s (org %s): %s -- %s",
            to_email,
            organization_id,
            title,
            body or "",
        )
        return

    import smtplib  # local import: only needed on the real path

    message = MIMEText(body or title, "plain")
    message["Subject"] = f"{SUBJECT_PREFIX} {title}"
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_user}>"
    message["To"] = to_email

    context = ssl.create_default_context()
    # smtplib is blocking -- run it off the event loop so the worker's
    # other jobs don't stall behind a slow SMTP server.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: _send_blocking(message, to_email),
    )


def _send_blocking(message: MIMEText, to_email: str) -> None:
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context) as server:
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_user, to_email, message.as_string())


async def send_notification_email(
    ctx: dict[str, Any],
    *,
    organization_id: str,
    to_email: str,
    event_key: str,
    title: str,
    body: str | None = None,
) -> dict[str, Any]:
    """Deliver one notification email, retrying up to MAX_ATTEMPTS."""
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            await _deliver(to_email, title, body, organization_id)
            return {"ok": True, "to": to_email, "event_key": event_key, "attempt": attempt}
        except Exception as exc:  # noqa: BLE001 -- retry any delivery failure
            last_error = exc
            logger.warning(
                "Notification email to %s failed (attempt %d/%d): %s",
                to_email,
                attempt,
                MAX_ATTEMPTS,
                exc,
            )
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(RETRY_DELAY_SECONDS)

    logger.error(
        "Notification email to %s failed after %d attempts: %s",
        to_email,
        MAX_ATTEMPTS,
        last_error,
    )
    return {"ok": False, "to": to_email, "event_key": event_key}
