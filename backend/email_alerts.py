import os
import smtplib
from email.mime.text import MIMEText

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD")

def send_email(to_email: str, subject: str, body: str):
    """Sends an email using Gmail SMTP service."""
    if not GMAIL_USER or not GMAIL_PASSWORD:
        print(f"[Email Alert] (Missing credentials/Mock output) To: {to_email} | Subject: {subject}")
        body_oneline = body.replace('\n', ' ')
        print(f"[Email Alert] Body: {body_oneline}")
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
        f"This is an automated alert from TrustAPI.\n"
        f"The API '{api_name}' ({api_url}) is currently reporting status: DOWN.\n\n"
        f"We will monitor the status and notify you when it recovers.\n\n"
        f"Best regards,\n"
        f"TrustAPI Monitor Team"
    )
    send_email(to_email, subject, body)

def send_recovery_alert(to_email: str, api_name: str):
    subject = f"✅ RECOVERY ALERT: {api_name} is back UP!"
    body = (
        f"Hello,\n\n"
        f"This is an automated notification from TrustAPI.\n"
        f"The API '{api_name}' has recovered and is now back UP and operational.\n\n"
        f"Best regards,\n"
        f"TrustAPI Monitor Team"
    )
    send_email(to_email, subject, body)

def send_failover_alert(to_email: str, api_name: str, backup_name: str):
    subject = f"⚠️ FAILOVER ACTIVATED: {api_name} switched to backup"
    body = (
        f"Hello,\n\n"
        f"This is an automated alert from TrustAPI.\n"
        f"The primary API '{api_name}' has failed {3} consecutive health checks.\n\n"
        f"Automated failover has been activated.\n"
        f"Traffic is now being directed to the backup: '{backup_name}'.\n\n"
        f"We will continue monitoring '{api_name}' and notify you when it recovers "
        f"and failover is cleared.\n\n"
        f"Best regards,\n"
        f"TrustAPI Monitor Team"
    )
    send_email(to_email, subject, body)


def send_failover_recovery_alert(to_email: str, api_name: str):
    subject = f"✅ FAILOVER CLEARED: {api_name} primary is stable again"
    body = (
        f"Hello,\n\n"
        f"This is an automated notification from TrustAPI.\n"
        f"The primary API '{api_name}' has passed {5} consecutive health checks "
        f"and is considered stable.\n\n"
        f"Failover has been cleared. The system has returned to the primary API.\n\n"
        f"Best regards,\n"
        f"TrustAPI Monitor Team"
    )
    send_email(to_email, subject, body)
