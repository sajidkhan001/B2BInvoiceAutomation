from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


APP_NAME = "B2BDocAutomation"


@dataclass(slots=True)
class MailSourceConfig:
    id: str
    kind: str = "imap"
    display_name: str = "Mail source"
    enabled: bool = True
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_mailbox: str = "INBOX"
    imap_search: str = "UNSEEN"
    gmail_client_secrets_file: str = ""
    gmail_query: str = "has:attachment is:unread"


@dataclass(slots=True)
class SheetsConfig:
    spreadsheet_id: str = ""
    oauth_client_secrets_file: str = ""


@dataclass(slots=True)
class AIConfig:
    fallback_enabled: bool = True
    provider: str = "openai"
    model: str = ""


@dataclass(slots=True)
class SecurityConfig:
    allow_unscanned_dev: bool = False
    clamav_host: str = "127.0.0.1"
    clamav_port: int = 3310


@dataclass(slots=True)
class AppConfig:
    poll_interval_seconds: int = 60
    start_with_windows: bool = False
    close_to_tray: bool = True
    mail_sources: list[MailSourceConfig] = field(default_factory=list)
    sheets: SheetsConfig = field(default_factory=SheetsConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)


def app_data_dir() -> Path:
    base = os.getenv("APPDATA")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".config"
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "config.json"

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return AppConfig(
            poll_interval_seconds=int(data.get("poll_interval_seconds", 60)),
            start_with_windows=bool(data.get("start_with_windows", False)),
            close_to_tray=bool(data.get("close_to_tray", True)),
            mail_sources=[MailSourceConfig(**item) for item in data.get("mail_sources", [])],
            sheets=SheetsConfig(**data.get("sheets", {})),
            ai=AIConfig(**data.get("ai", {})),
            security=SecurityConfig(**data.get("security", {})),
        )

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")


def set_start_with_windows(enabled: bool, command: str | None = None) -> None:
    if sys.platform != "win32":
        return
    import winreg

    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            if command:
                value = command
            elif getattr(sys, "frozen", False):
                value = f'"{sys.executable}"'
            else:
                value = f'"{sys.executable}" -m b2bdoc.desktop.main'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, value)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                return
