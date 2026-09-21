import random
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings


def generate_verification_code() -> str:
    """A random 6-digit code, e.g. '042917'."""
    return f"{random.randint(0, 999999):06d}"


def send_verification_email(to_email: str, name: str, code: str) -> None:
    """Emails the verification code via SMTP (Gmail by default).

    If SMTP_USER/SMTP_PASSWORD aren't set in backend/.env, this just prints
    the code to the server console instead of raising -- so registration
    still works locally before a teammate sets up SMTP.
    """
    if not settings.smtp_user or not settings.smtp_password:
        print(
            f"[SentinelX] SMTP not configured -- verification code for "
            f"{to_email}: {code}"
        )
        return

    message = MIMEMultipart("alternative")
    message["Subject"] = "Verify your SentinelX account"
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_user}>"
    message["To"] = to_email

    text_body = (
        f"Hi {name},\n\n"
        f"Your SentinelX verification code is: {code}\n\n"
        f"This code expires in 10 minutes.\n\n"
        f"If you didn't create a SentinelX account, you can ignore this email."
    )

    html_body = f"""
    <div style="font-family: Arial, sans-serif; color: #0b1f33;">
      <p>Hi {name},</p>
      <p>Your SentinelX verification code is:</p>
      <p style="font-size: 28px; font-weight: bold; letter-spacing: 6px;">{code}</p>
      <p>This code expires in 10 minutes.</p>
      <p style="color: #888;">If you didn't create a SentinelX account, you can ignore this email.</p>
    </div>
    """

    message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context) as server:
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_user, to_email, message.as_string())


def send_password_reset_email(to_email: str, name: str, code: str) -> None:
    """Emails a password-reset code via SMTP (Gmail by default).

    Same fallback as send_verification_email: if SMTP isn't configured,
    the code is printed to the server console instead.
    """
    if not settings.smtp_user or not settings.smtp_password:
        print(
            f"[SentinelX] SMTP not configured -- password reset code for "
            f"{to_email}: {code}"
        )
        return

    message = MIMEMultipart("alternative")
    message["Subject"] = "Reset your SentinelX password"
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_user}>"
    message["To"] = to_email

    text_body = (
        f"Hi {name},\n\n"
        f"Your SentinelX password reset code is: {code}\n\n"
        f"This code expires in 10 minutes.\n\n"
        f"If you didn't request a password reset, you can ignore this email --"
        f" your password will stay the same."
    )

    html_body = f"""
    <div style="font-family: Arial, sans-serif; color: #0b1f33;">
      <p>Hi {name},</p>
      <p>Your SentinelX password reset code is:</p>
      <p style="font-size: 28px; font-weight: bold; letter-spacing: 6px;">{code}</p>
      <p>This code expires in 10 minutes.</p>
      <p style="color: #888;">If you didn't request a password reset, you can ignore this email -- your password will stay the same.</p>
    </div>
    """

    message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context) as server:
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_user, to_email, message.as_string())


def send_invitation_email(
    to_email: str,
    organization_name: str,
    role_label: str,
    invite_link: str,
    expires_at,
) -> None:
    """Emails an invitation link via SMTP (Gmail by default).

    Same fallback as the other senders in this file: if SMTP isn't
    configured, the link is printed to the server console instead of
    raising, so the invite -> accept flow still works locally before a
    teammate sets up SMTP.
    """
    expires_label = expires_at.strftime("%B %d, %Y")

    if not settings.smtp_user or not settings.smtp_password:
        print(
            f"[SentinelX] SMTP not configured -- invitation link for "
            f"{to_email} ({organization_name}, {role_label}): {invite_link} "
            f"(expires {expires_label})"
        )
        return

    message = MIMEMultipart("alternative")
    message["Subject"] = f"You've been invited to {organization_name} on SentinelX"
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_user}>"
    message["To"] = to_email

    text_body = (
        f"You've been invited to join {organization_name} on SentinelX as "
        f"{role_label}.\n\n"
        f"Accept the invitation: {invite_link}\n\n"
        f"This invitation expires on {expires_label}.\n\n"
        f"If you weren't expecting this, you can ignore this email."
    )

    html_body = f"""
    <div style="font-family: Arial, sans-serif; color: #0b1f33;">
      <p>You've been invited to join <strong>{organization_name}</strong> on SentinelX as <strong>{role_label}</strong>.</p>
      <p><a href="{invite_link}" style="display: inline-block; padding: 10px 20px; background: #1f6feb; color: #fff; text-decoration: none; border-radius: 6px;">Accept invitation</a></p>
      <p style="color: #888;">This invitation expires on {expires_label}.</p>
      <p style="color: #888;">If you weren't expecting this, you can ignore this email.</p>
    </div>
    """

    message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context) as server:
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_user, to_email, message.as_string())
