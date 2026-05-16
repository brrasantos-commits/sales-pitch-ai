import smtplib
import logging
from email.mime.text import MIMEText
from typing import Optional
import os
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def send_reset_email(to_email: str, reset_link: str, db: Optional[Session] = None, user_id: Optional[int] = None):
    """
    Send password reset email using SendGrid or SMTP
    Tries SendGrid first (works on Railway), falls back to SMTP
    """
    
    # Try SendGrid first (recommended for Railway)
    sendgrid_key = os.getenv("SENDGRID_API_KEY")
    if sendgrid_key:
        return _send_via_sendgrid(to_email, reset_link, sendgrid_key, db, user_id)
    
    # Fallback to SMTP
    return _send_via_smtp(to_email, reset_link, db, user_id)


def _send_via_sendgrid(to_email: str, reset_link: str, api_key: str, db: Optional[Session] = None, user_id: Optional[int] = None):
    """Send email via SendGrid API"""
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email, To, Content
        
        from_email = os.getenv("SENDGRID_FROM_EMAIL", "noreply@salespitchai.com")
        from_name = os.getenv("SENDGRID_FROM_NAME", "Sales Pitch AI")
        
        message = Mail(
            from_email=Email(from_email, from_name),
            to_emails=To(to_email),
            subject="Redefinição de senha - Sales Pitch AI",
            html_content=Content("text/html", f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #007bff; color: white; padding: 20px; text-align: center; }}
        .content {{ background: #f9f9f9; padding: 30px; }}
        .button {{ 
            display: inline-block; 
            padding: 12px 30px; 
            background: #007bff; 
            color: white; 
            text-decoration: none; 
            border-radius: 5px;
            margin: 20px 0;
        }}
        .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Sales Pitch AI</h1>
        </div>
        <div class="content">
            <h2>Redefinição de Senha</h2>
            <p>Olá,</p>
            <p>Você solicitou a redefinição de senha no Sales Pitch AI.</p>
            <p>Clique no botão abaixo para redefinir sua senha:</p>
            <p style="text-align: center;">
                <a href="{reset_link}" class="button">Redefinir Senha</a>
            </p>
            <p>Ou copie e cole este link no seu navegador:</p>
            <p style="word-break: break-all; background: #fff; padding: 10px; border: 1px solid #ddd;">
                {reset_link}
            </p>
            <p><strong>Este link expira em 1 hora.</strong></p>
            <p>Se você não solicitou esta redefinição, ignore este email.</p>
        </div>
        <div class="footer">
            <p>© 2024 Sales Pitch AI - Todos os direitos reservados</p>
        </div>
    </div>
</body>
</html>
            """)
        )
        
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        
        # Log usage
        if db:
            try:
                from pitch_app.services.usage_tracking_service import log_sendgrid_usage
                log_sendgrid_usage(
                    db=db,
                    operation="password_reset_email",
                    user_id=user_id,
                    metadata={"to_email": to_email, "status_code": response.status_code}
                )
            except Exception as log_error:
                logger.warning(f"Failed to log SendGrid usage: {log_error}")
        
        logger.info(f"Reset email sent via SendGrid to {to_email} (status: {response.status_code})")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email via SendGrid to {to_email}: {e}")
        raise


def _send_via_smtp(to_email: str, reset_link: str, db: Optional[Session] = None, user_id: Optional[int] = None):
    """Send email via SMTP (fallback)"""
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)

    # Verificar se configurações SMTP estão presentes
    if not all([smtp_host, smtp_user, smtp_password]):
        logger.warning("Neither SendGrid nor SMTP configured. Email not sent.")
        logger.info(f"Reset link for {to_email}: {reset_link}")
        return False

    subject = "Redefinição de senha - Sales Pitch AI"
    body = f"""
Olá,

Você solicitou a redefinição de senha no Sales Pitch AI.

Clique no link abaixo para redefinir sua senha:

{reset_link}

Este link expira em 1 hora.

Se você não solicitou esta redefinição, ignore este email.

---
Sales Pitch AI
"""

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = smtp_from or smtp_user
        msg["To"] = to_email

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        
        logger.info(f"Reset email sent via SMTP to {to_email}")
        return True
    
    except Exception as e:
        logger.error(f"Failed to send email via SMTP to {to_email}: {e}")
        raise

# Made with Bob
