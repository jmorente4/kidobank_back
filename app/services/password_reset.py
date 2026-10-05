import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_password_reset_email(recipient: str, reset_url: str) -> None:
    message = EmailMessage()
    message["Subject"] = "Restablecer contraseña de Kidobank"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = recipient
    message.set_content(
        "Hemos recibido una solicitud para restablecer tu contraseña de Kidobank.\n\n"
        f"Usa este enlace para elegir una contraseña nueva (válido durante una hora):\n{reset_url}\n\n"
        "Si no solicitaste este cambio, puedes ignorar este mensaje."
    )

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls(context=ssl.create_default_context())
            if settings.SMTP_USERNAME:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.exception("No se pudo enviar el correo de restablecimiento de contraseña")
