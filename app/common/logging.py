"""구조화 로깅 설정 (컨테이너 친화 stdout).

사용자 노출 텍스트는 한국어 정책이나 로그는 운영용이므로 영문/식별자 무방 (plan §6.3).
"""

from __future__ import annotations

import logging
from logging.config import dictConfig

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """stdlib dictConfig 로 stdout 핸들러 1개 설정 (멱등)."""
    global _CONFIGURED
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                },
            },
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "default",
                },
            },
            "root": {
                "level": level.upper(),
                "handlers": ["stdout"],
            },
        }
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """이름 있는 로거 반환 (미설정 시 기본 INFO 로 1회 설정)."""
    if not _CONFIGURED:
        configure_logging()
    return logging.getLogger(name)
