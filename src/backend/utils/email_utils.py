# -*- coding: utf-8 -*-
#  Copyright (C) 2026 FjiNeko
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
import logging


try:
    import certifi
    _CERTIFI_AVAILABLE = True
except Exception:
    certifi = None
    _CERTIFI_AVAILABLE = False

logger = logging.getLogger(__name__)


def _get_smtp_config():
    """
    Read SMTP configuration from environment variables.
    """
    host = os.getenv("SMTP_HOST", None)
    port = int(os.getenv("SMTP_PORT", None))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    mail_from = os.getenv("MAIL_FROM", user or None)
    mail_from_name = os.getenv("MAIL_FROM_NAME", None)
    return host, port, user, password, mail_from, mail_from_name


def _build_ssl_context():
    """Build a TLS context with the best available CA bundle.

    Priority:
    1) SMTP_TLS_INSECURE=1 -> disable verification (DEV ONLY; not recommended)
    2) SMTP_TLS_CAFILE -> use custom CA file path if provided
    3) certifi bundle -> reliable CA store inside the Python env
    4) system default -> fallback
    """
    insecure = os.getenv("SMTP_TLS_INSECURE", "0").lower() in ("1", "true", "yes")
    cafile = os.getenv("SMTP_TLS_CAFILE")

    try:
        if insecure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx

        if cafile and os.path.exists(cafile):
            return ssl.create_default_context(cafile=cafile)

        if _CERTIFI_AVAILABLE:
            return ssl.create_default_context(cafile=certifi.where())

        return ssl.create_default_context()
    except Exception as e:
        logger.warning("Failed to build TLS context: %s. Falling back to default context.", e)
        return ssl.create_default_context()


def send_email(subject: str, to_email: str, html_content: str, text_content: str = None):
    """Send an email using Zoho SMTP (or configured SMTP).

    Falls back to log-only if SMTP_USER/PASS are not configured.
    """
    host, port, user, password, mail_from, mail_from_name = _get_smtp_config()
    use_ssl = os.getenv("SMTP_USE_SSL", "0").lower() in ("1", "true", "yes")

    if not user or not password or not mail_from:
        logger.warning("SMTP is not fully configured; email will not be sent. Subject: %s, To: %s", subject, to_email)
        logger.info("Email preview (HTML) to %s: %s", to_email, html_content)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((mail_from_name, mail_from))
    msg["To"] = to_email

    if text_content:
        msg.attach(MIMEText(text_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        context = _build_ssl_context()

        if use_ssl:
            # SMTPS (implicit TLS), e.g. Zoho port 465
            with smtplib.SMTP_SSL(host, port, context=context) as server:
                server.login(user, password)
                server.sendmail(mail_from, [to_email], msg.as_string())
        else:
            # STARTTLS on port 587 (Zoho default)
            with smtplib.SMTP(host, port) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(user, password)
                server.sendmail(mail_from, [to_email], msg.as_string())

        logger.info("Email sent to %s: %s", to_email, subject)
        return True
    except ssl.SSLCertVerificationError as e:
        logger.error(
            "TLS verification failed when sending to %s via %s:%s - %s. "
            "If this is a production server, ensure OS CA certificates are installed (e.g. 'ca-certificates'). "
            "Alternatively set SMTP_TLS_CAFILE to a valid CA bundle or enable SMTP_USE_SSL and port 465.",
            to_email, host, port, e, exc_info=True
        )
        return False
    except Exception as e:
        logger.error("Failed to send email to %s via SMTP %s:%s - %s", to_email, host, port, e, exc_info=True)
        return False


def send_password_reset_email(to_email: str, reset_link: str):
    """Send a password reset email with both HTML and text versions."""
    subject = "CGBGEAR 密码重置"
    text_body = (
        "您好，\n\n"
        "我们收到了您的密码重置请求。如果这不是您本人的操作，请忽略此邮件。\n\n"
        f"请在 15 分钟内点击以下链接重置您的密码：\n{reset_link}\n\n"
        "如果链接无法点击，请复制到浏览器中打开。\n\n"
        "CGBGEAR 团队"
    )

    template_path = os.path.join(os.path.dirname(__file__), "1.html")
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            html_template = f.read()
        html_body = html_template.format(reset_link=reset_link)
    except Exception as e:
        # Fallback to a minimal inline HTML if reading the template fails
        logger.warning("Failed to load email HTML template %s: %s; using fallback.", template_path, e)
        html_body = f"""
        <div style='font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#333;'>
          <p>您好，</p>
          <p>我们收到了您的密码重置请求。如果这不是您本人的操作，请忽略此邮件。</p>
          <p>请在 <strong>15 分钟</strong> 内点击以下按钮重置您的密码：</p>
          <p>
            <a href="{reset_link}" style="display:inline-block;background:#1a73e8;color:#fff;padding:10px 16px;border-radius:4px;text-decoration:none;">
              立即重置密码
            </a>
          </p>
          <p>如果按钮无法点击，请复制以下链接到浏览器中打开：</p>
          <p><a href="{reset_link}">{reset_link}</a></p>
          <p>祝使用愉快！<br/>CGBGEAR 团队</p>
        </div>
        """
    return send_email(subject, to_email, html_body, text_body)
