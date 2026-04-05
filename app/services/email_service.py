import smtplib
from email.mime.text import MIMEText


def send_email(to_email: str, subject: str, body: str):
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = "no-reply@eventapp.com"
        msg["To"] = to_email

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login("YOUR_EMAIL", "YOUR_APP_PASSWORD")
            server.send_message(msg)

    except Exception as e:
        print("Email failed:", e)