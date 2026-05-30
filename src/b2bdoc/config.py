from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


@dataclass(frozen=True, slots=True)
class Settings:
    max_file_mb: int = 25
    max_pages: int = 50
    max_inflight_mb: int = 512
    max_inflight_ram_fraction: float = 0.40
    confidence_threshold: float = 0.90
    parser_workers: int = max(1, min(4, (os.cpu_count() or 2) - 1))
    ocr_workers: int = 4
    queue_multiplier: int = 2
    allow_heic: bool = False
    allow_unscanned_dev: bool = False
    parser_timeout_seconds: int = 45

    clamav_host: str = "127.0.0.1"
    clamav_port: int = 3310
    clamav_timeout_seconds: int = 15

    imap_host: str | None = None
    imap_port: int = 993
    imap_user: str | None = None
    imap_password: str | None = None
    imap_mailbox: str = "INBOX"
    imap_search: str = "UNSEEN"

    google_sheet_id: str | None = None
    google_service_account_file: str | None = None
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_fallback_enabled: bool = False
    poll_interval_seconds: int = 60

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @property
    def max_inflight_bytes(self) -> int:
        return self.max_inflight_mb * 1024 * 1024

    @property
    def queue_size(self) -> int:
        return max(1, self.parser_workers * self.queue_multiplier)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            max_file_mb=_env_int("B2B_MAX_FILE_MB", 25),
            max_pages=_env_int("B2B_MAX_PAGES", 50),
            max_inflight_mb=_env_int("B2B_MAX_INFLIGHT_MB", 512),
            max_inflight_ram_fraction=_env_float("B2B_MAX_INFLIGHT_RAM_FRACTION", 0.40),
            confidence_threshold=_env_float("B2B_CONFIDENCE_THRESHOLD", 0.90),
            parser_workers=_env_int(
                "B2B_PARSER_WORKERS", max(1, min(4, (os.cpu_count() or 2) - 1))
            ),
            ocr_workers=_env_int("B2B_OCR_WORKERS", 4),
            queue_multiplier=_env_int("B2B_QUEUE_MULTIPLIER", 2),
            allow_heic=_env_bool("B2B_ALLOW_HEIC", False),
            allow_unscanned_dev=_env_bool("B2B_ALLOW_UNSCANNED_DEV", False),
            parser_timeout_seconds=_env_int("B2B_PARSER_TIMEOUT_SECONDS", 45),
            clamav_host=os.getenv("B2B_CLAMAV_HOST", "127.0.0.1"),
            clamav_port=_env_int("B2B_CLAMAV_PORT", 3310),
            clamav_timeout_seconds=_env_int("B2B_CLAMAV_TIMEOUT_SECONDS", 15),
            imap_host=os.getenv("B2B_IMAP_HOST") or None,
            imap_port=_env_int("B2B_IMAP_PORT", 993),
            imap_user=os.getenv("B2B_IMAP_USER") or None,
            imap_password=os.getenv("B2B_IMAP_PASSWORD") or None,
            imap_mailbox=os.getenv("B2B_IMAP_MAILBOX", "INBOX"),
            imap_search=os.getenv("B2B_IMAP_SEARCH", "UNSEEN"),
            google_sheet_id=os.getenv("B2B_GOOGLE_SHEET_ID") or None,
            google_service_account_file=os.getenv("B2B_GOOGLE_SERVICE_ACCOUNT_FILE") or None,
            ai_provider=os.getenv("B2B_AI_PROVIDER") or None,
            ai_model=os.getenv("B2B_AI_MODEL") or None,
            ai_fallback_enabled=_env_bool("B2B_AI_FALLBACK_ENABLED", False),
            poll_interval_seconds=_env_int("B2B_POLL_INTERVAL_SECONDS", 60),
        )
