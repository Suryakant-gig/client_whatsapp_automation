"""Application logging configuration."""

import logging
import sys
from typing import Optional


def setup_logging(log_level: Optional[str] = "INFO") -> None:
    """Configure centralized application logging.

    Args:
        log_level: Desired log level string (e.g., 'DEBUG', 'INFO', 'WARNING', 'ERROR').
    """
    normalized_level = getattr(logging, (log_level or "INFO").upper(), logging.INFO)

    log_format = "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(normalized_level)

    # Avoid duplicate handlers if setup_logging is invoked multiple times
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(normalized_level)
        formatter = logging.Formatter(fmt=log_format, datefmt=date_format)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setLevel(normalized_level)
            formatter = logging.Formatter(fmt=log_format, datefmt=date_format)
            handler.setFormatter(formatter)

    # Ensure application logger inherits level and handlers
    app_logger = logging.getLogger("app")
    app_logger.setLevel(normalized_level)
