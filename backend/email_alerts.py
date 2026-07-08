import os
import smtplib
from email.mime.text import MIMEText

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD")

def send_email(to_email: str, subject: str, body: str):
    """Sends an email using Gmail SMTP service."""
    if not GMAIL_USER or not GMAIL_PASSWORD:
        print(f"[Email Alert] (Missing credentials/Mock output) To: {to_email} | Subject: {subject}")
        print(f"[Email Alert] Body: {body.replace('\n', ' ')}")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = to_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, [to_email], msg.as_string())
        print(f"[Email Alert] Email successfully sent to {to_email}")
    except Exception as e:
        print(f"[Email Alert] Failed to send email to {to_email}: {e}")

def send_alert(to_email: str, api_name: str, api_url: str):
    subject = f"🚨 OUTAGE ALERT: {api_name} is DOWN!"
    body = (
        f"Hello,\n\n"
        f"This is an automated alert from PulseGuard.\n"
        f"The API '{api_name}' ({api_url}) is currently reporting status: DOWN.\n\n"
        f"We will monitor the status and notify you when it recovers.\n\n"
        f"Best regards,\n"
        f"PulseGuard Monitor Team"
    )
    send_email(to_email, subject, body)

def send_recovery_alert(to_email: str, api_name: str):
    subject = f"✅ RECOVERY ALERT: {api_name} is back UP!"
    body = (
        f"Hello,\n\n"
        f"This is an automated notification from PulseGuard.\n"
        f"The API '{api_name}' has recovered and is now back UP and operational.\n\n"
        f"Best regards,\n"
        f"PulseGuard Monitor Team"
    )
    send_email(to_email, subject, body)
