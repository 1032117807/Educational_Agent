import logging

from app.core.logging import SensitiveDataFilter


def test_sensitive_logging_filter_redacts_secrets():
    record = logging.LogRecord("test", logging.INFO, "", 1, "api_key=abc token:xyz safe=1", (), None)
    assert SensitiveDataFilter().filter(record)
    message = record.getMessage()
    assert "abc" not in message and "xyz" not in message
    assert message.count("[REDACTED]") == 2
