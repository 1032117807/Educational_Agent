from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from app.core.config import AppSettings


class SensitiveDataFilter(logging.Filter):
    PATTERN = re.compile(
        r"(?i)\b(api[_-]?key|token|password|secret)\b\s*[:=]\s*([^\s,;]+)"
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        sanitized = self.PATTERN.sub(r"\1=[REDACTED]", message)
        if sanitized != message:
            record.msg = sanitized
            record.args = ()
        return True


def configure_logging(config: AppSettings) -> None:
    config.ensure_directories()
    handler = RotatingFileHandler(
        config.log_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(SensitiveDataFilter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
