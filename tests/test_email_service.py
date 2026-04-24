import pytest
from unittest.mock import patch, MagicMock
from app.services.email_service import send_email
from app.core.config import settings


class TestEmailService:
    @patch("app.services.email_service.smtplib.SMTP")
    def test_send_email_success(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        send_email("test@example.com", "Hello", "Body content")

        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with(settings.SMTP_USER, settings.SMTP_PASSWORD)
        mock_server.send_message.assert_called_once()

        msg_arg = mock_server.send_message.call_args[0][0]
        assert msg_arg["Subject"] == "Hello"
        assert msg_arg["To"] == "test@example.com"
        assert msg_arg["From"] == settings.EMAIL_FROM

    @patch("app.services.email_service.smtplib.SMTP")
    def test_send_email_exception_handling(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_server.login.side_effect = Exception("SMTP Auth Failed")
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        # Should not raise — failures are logged, not printed
        import logging
        with patch("app.services.email_service.logger") as mock_logger:
            send_email("test@example.com", "Hello", "Body content")
            mock_logger.error.assert_called_once()
            assert "SMTP Auth Failed" in str(mock_logger.error.call_args)
