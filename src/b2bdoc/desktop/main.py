from __future__ import annotations

import sys
import multiprocessing
from dataclasses import replace

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from b2bdoc.ai.providers import ProviderAIFallback
from b2bdoc.config import Settings
from b2bdoc.desktop.secrets import KeyringSecretStore, SecretStore, ai_api_key, imap_password_key
from b2bdoc.desktop.settings_store import AppConfig, MailSourceConfig, SettingsStore
from b2bdoc.desktop.windows import MainWindow
from b2bdoc.imap_ingest import IMAPIngestor
from b2bdoc.integrations.google_oauth import SHEETS_SCOPES, load_credentials
from b2bdoc.mail.gmail_oauth import GmailOAuthSource
from b2bdoc.memory import BoundedMemoryManager
from b2bdoc.pipeline import DocumentPipeline
from b2bdoc.sheets import GoogleSheetsLedger, NullLedgerWriter
from b2bdoc.worker.scheduler import AutomationScheduler, SchedulerEvent


class DesktopEvents(QObject):
    scheduler_event = Signal(object)


class DesktopController:
    def __init__(
        self,
        *,
        settings_store: SettingsStore | None = None,
        secret_store: SecretStore | None = None,
    ) -> None:
        self.settings_store = settings_store or SettingsStore()
        self.secret_store = secret_store or KeyringSecretStore()
        self.config = self.settings_store.load()
        self.events = DesktopEvents()
        self.scheduler = AutomationScheduler(
            poll_callback=self.poll_once,
            interval_seconds=self.config.poll_interval_seconds,
            event_callback=self.events.scheduler_event.emit,
        )

    def reload(self) -> AppConfig:
        self.config = self.settings_store.load()
        self.scheduler.interval_seconds = self.config.poll_interval_seconds
        return self.config

    def save_config(self, config: AppConfig) -> None:
        self.config = config
        self.settings_store.save(config)
        self.scheduler.interval_seconds = config.poll_interval_seconds

    def poll_once(self):
        config = self.reload()
        memory = BoundedMemoryManager(Settings().max_file_bytes, Settings().max_inflight_bytes)
        pipeline = self._build_pipeline(config)
        results = []
        for source in config.mail_sources:
            if not source.enabled:
                continue
            if source.kind == "imap":
                results.extend(self._poll_imap_source(source, memory, pipeline, config))
            elif source.kind == "gmail":
                results.extend(self._poll_gmail_source(source, memory, pipeline))
        return results

    def _base_settings(self, config: AppConfig) -> Settings:
        return Settings(
            allow_unscanned_dev=config.security.allow_unscanned_dev,
            clamav_host=config.security.clamav_host,
            clamav_port=config.security.clamav_port,
            google_sheet_id=config.sheets.spreadsheet_id or None,
            ai_provider=config.ai.provider,
            ai_model=config.ai.model or None,
            ai_fallback_enabled=config.ai.fallback_enabled,
            poll_interval_seconds=config.poll_interval_seconds,
        )

    def _build_pipeline(self, config: AppConfig) -> DocumentPipeline:
        settings = self._base_settings(config)
        ledger = self._build_ledger(config)
        ai_fallback = self._build_ai_fallback(config)
        return DocumentPipeline(settings=settings, ledger_writer=ledger, ai_fallback=ai_fallback)

    def _build_ledger(self, config: AppConfig):
        if config.sheets.spreadsheet_id and config.sheets.oauth_client_secrets_file:
            credentials = load_credentials(
                config.sheets.oauth_client_secrets_file,
                SHEETS_SCOPES,
                self.secret_store,
                "sheets",
            )
            return GoogleSheetsLedger.from_credentials(config.sheets.spreadsheet_id, credentials)
        return NullLedgerWriter()

    def _build_ai_fallback(self, config: AppConfig):
        if not config.ai.fallback_enabled or not config.ai.provider or not config.ai.model:
            return None
        key = self.secret_store.get(ai_api_key(config.ai.provider))
        if not key:
            return None
        return ProviderAIFallback(config.ai.provider, key, config.ai.model)

    def _poll_imap_source(
        self,
        source: MailSourceConfig,
        memory: BoundedMemoryManager,
        pipeline: DocumentPipeline,
        config: AppConfig,
    ):
        password = self.secret_store.get(imap_password_key(source.id))
        if not password:
            raise ValueError(f"IMAP password missing for {source.display_name}")
        settings = replace(
            self._base_settings(config),
            imap_host=source.imap_host,
            imap_port=source.imap_port,
            imap_user=source.imap_user,
            imap_password=password,
            imap_mailbox=source.imap_mailbox,
            imap_search=source.imap_search,
        )
        return IMAPIngestor(settings, memory, pipeline).run_once()

    def _poll_gmail_source(
        self,
        source: MailSourceConfig,
        memory: BoundedMemoryManager,
        pipeline: DocumentPipeline,
    ):
        gmail = GmailOAuthSource(
            client_secrets_file=source.gmail_client_secrets_file,
            secret_store=self.secret_store,
            query=source.gmail_query,
            memory=memory,
        )
        envelopes = gmail.iter_envelopes()
        return [pipeline.process(envelope, actor=f"gmail:{source.id}") for envelope in envelopes]


class DesktopApp:
    def __init__(self) -> None:
        self.qt_app = QApplication.instance() or QApplication(sys.argv)
        self.qt_app.setQuitOnLastWindowClosed(False)
        self.controller = DesktopController()
        self.window = MainWindow(self.controller)
        self.exiting = False
        self.tray = self._build_tray()
        self.window.exit_requested.connect(self.exit)
        self.controller.events.scheduler_event.connect(self._on_scheduler_event)

    def run(self) -> int:
        self.tray.show()
        self.window.show()
        if self.controller.config.start_with_windows:
            self.controller.scheduler.start()
        return self.qt_app.exec()

    def exit(self) -> None:
        self.exiting = True
        self.controller.scheduler.stop()
        self.tray.hide()
        self.qt_app.quit()

    def _build_tray(self) -> QSystemTrayIcon:
        icon = self.qt_app.style().standardIcon(self.qt_app.style().StandardPixmap.SP_ComputerIcon)
        tray = QSystemTrayIcon(icon, self.qt_app)
        tray.setToolTip("B2B Invoice Automation")
        menu = QMenu()
        show_action = menu.addAction("Open")
        show_action.triggered.connect(self.window.show_normal)
        pause_action = menu.addAction("Pause / Resume")
        pause_action.triggered.connect(self.window.toggle_scheduler)
        exit_action = menu.addAction("Exit")
        exit_action.triggered.connect(self.exit)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: self.window.show_normal())
        return tray

    def _on_scheduler_event(self, event: SchedulerEvent) -> None:
        if event.level == "error":
            self.tray.setToolTip(f"B2B Invoice Automation - Error: {event.message}")
            self.tray.showMessage("Invoice automation error", event.message, QSystemTrayIcon.MessageIcon.Critical, 5000)
        elif event.level == "warning":
            self.tray.setToolTip("B2B Invoice Automation - Needs review")
            self.tray.showMessage("Invoice needs review", event.message, QSystemTrayIcon.MessageIcon.Warning, 4000)
        else:
            self.tray.setToolTip(f"B2B Invoice Automation - {self.controller.scheduler.last_status}")


def main() -> int:
    multiprocessing.freeze_support()
    return DesktopApp().run()


if __name__ == "__main__":
    raise SystemExit(main())
