import pytest
from unittest.mock import patch, MagicMock
from app.services.email_service import send_email

class TestEmailService:
    @patch("app.services.email_service.smtplib.SMTP")
    def test_send_email_success(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        send_email("test@example.com", "Hello", "Body content")

        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("YOUR_EMAIL", "YOUR_APP_PASSWORD")
        mock_server.send_message.assert_called_once()
        
        # Verify the MIMEText object passed to send_message
        msg_arg = mock_server.send_message.call_args[0][0]
        assert msg_arg["Subject"] == "Hello"
        assert msg_arg["To"] == "test@example.com"
        assert msg_arg["From"] == "no-reply@eventapp.com"

    @patch("app.services.email_service.smtplib.SMTP")
    def test_send_email_exception_handling(self, mock_smtp_class, capsys):
        mock_server = MagicMock()
        mock_server.login.side_effect = Exception("SMTP Auth Failed")
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        # Should not raise, just print
        send_email("test@example.com", "Hello", "Body content")
        
        captured = capsys.readouterr()
        assert "Email failed: SMTP Auth Failed" in captured.out