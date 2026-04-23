"""
Tests SMTP connection and sends a real email directly.
Run with: python test_smtp.py
"""
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

from app.core.config import settings

print(f"SMTP_HOST     : {settings.SMTP_HOST}")
print(f"SMTP_PORT     : {settings.SMTP_PORT}")
print(f"SMTP_USER     : {settings.SMTP_USER}")
print(f"SMTP_PASSWORD : {'SET (' + settings.SMTP_PASSWORD[:4] + '...)' if settings.SMTP_PASSWORD else 'NOT SET'}")
print(f"EMAIL_FROM    : {settings.EMAIL_FROM}")
print()

TO = settings.SMTP_USER  # send to yourself

try:
    print("Connecting to SMTP server...")
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.set_debuglevel(1)  # prints every SMTP command/response
        print("Running STARTTLS...")
        server.starttls()
        print(f"Logging in as {settings.SMTP_USER}...")
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        print("Login successful. Sending email...")

        msg = MIMEText("This is a test email from the E-VENT reminder system.")
        msg["Subject"] = "E-VENT SMTP Test"
        msg["From"] = settings.EMAIL_FROM
        msg["To"] = TO

        server.send_message(msg)
        print(f"\n✓ Email sent successfully to {TO}")

except smtplib.SMTPAuthenticationError as e:
    print(f"\n✗ Authentication failed: {e}")
    print("  → Check SMTP_USER and SMTP_PASSWORD in your .env")
    print("  → Make sure you're using a Gmail App Password, not your regular password")
    print("  → Generate one at: https://myaccount.google.com/apppasswords")

except smtplib.SMTPException as e:
    print(f"\n✗ SMTP error: {e}")

except Exception as e:
    print(f"\n✗ Unexpected error: {e}")
