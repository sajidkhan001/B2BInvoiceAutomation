from __future__ import annotations

import uuid

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from b2bdoc.ai.providers import AIProviderClient, AIProviderError
from b2bdoc.desktop.secrets import ai_api_key, imap_password_key
from b2bdoc.desktop.settings_store import AppConfig, MailSourceConfig, set_start_with_windows
from b2bdoc.integrations.google_oauth import GMAIL_SCOPES, SHEETS_SCOPES, credential_name_for_file, run_oauth_flow


class MainWindow(QMainWindow):
    exit_requested = Signal()

    def __init__(self, controller) -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("B2B Invoice Automation")
        self.resize(980, 680)
        self._closing_to_tray = True
        self._build_ui()
        self._load_config()
        self.controller.events.scheduler_event.connect(self._append_event)

    def show_normal(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def toggle_scheduler(self) -> None:
        scheduler = self.controller.scheduler
        if not scheduler.is_running:
            scheduler.start()
        elif scheduler.is_paused:
            scheduler.resume()
        else:
            scheduler.pause()
        self._refresh_dashboard()

    def closeEvent(self, event) -> None:
        if self.controller.config.close_to_tray and self._closing_to_tray:
            event.ignore()
            self.hide()
            return
        event.accept()

    def _build_ui(self) -> None:
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._build_dashboard_tab()
        self._build_mail_tab()
        self._build_sheets_tab()
        self._build_ai_tab()
        self._build_review_tab()
        self._build_logs_tab()
        self._build_security_tab()

    def _build_dashboard_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.status_label = QLabel("Stopped")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.start_button = QPushButton("Start Automation")
        self.pause_button = QPushButton("Pause / Resume")
        self.run_once_button = QPushButton("Run Once")
        self.exit_button = QPushButton("Exit Completely")
        self.start_button.clicked.connect(self._start_scheduler)
        self.pause_button.clicked.connect(self.toggle_scheduler)
        self.run_once_button.clicked.connect(self._run_once)
        self.exit_button.clicked.connect(self.exit_requested.emit)
        layout.addWidget(QLabel("Automation Status"))
        layout.addWidget(self.status_label)
        layout.addWidget(self.start_button)
        layout.addWidget(self.pause_button)
        layout.addWidget(self.run_once_button)
        layout.addStretch()
        layout.addWidget(self.exit_button)
        self.tabs.addTab(tab, "Dashboard")

    def _build_mail_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.mail_kind = QComboBox()
        self.mail_kind.addItems(["imap", "gmail"])
        self.mail_name = QLineEdit()
        self.mail_host = QLineEdit()
        self.mail_port = QSpinBox()
        self.mail_port.setRange(1, 65535)
        self.mail_port.setValue(993)
        self.mail_user = QLineEdit()
        self.mail_password = QLineEdit()
        self.mail_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.mailbox = QLineEdit("INBOX")
        self.mail_search = QLineEdit("UNSEEN")
        self.gmail_client_file = QLineEdit()
        browse_gmail = QPushButton("Browse Gmail OAuth JSON")
        browse_gmail.clicked.connect(lambda: self._browse_file(self.gmail_client_file))
        save_mail = QPushButton("Save Mail Source")
        save_mail.clicked.connect(self._save_mail_source)
        connect_gmail = QPushButton("Connect Gmail OAuth")
        connect_gmail.clicked.connect(self._connect_gmail)
        self.mail_sources = QListWidget()
        form = QFormLayout()
        form.addRow("Type", self.mail_kind)
        form.addRow("Display name", self.mail_name)
        form.addRow("IMAP host", self.mail_host)
        form.addRow("IMAP port", self.mail_port)
        form.addRow("IMAP user", self.mail_user)
        form.addRow("IMAP password", self.mail_password)
        form.addRow("Mailbox", self.mailbox)
        form.addRow("Search", self.mail_search)
        form.addRow("Gmail OAuth JSON", self.gmail_client_file)
        layout.addLayout(form)
        layout.addWidget(browse_gmail)
        layout.addWidget(connect_gmail)
        layout.addWidget(save_mail)
        layout.addWidget(QLabel("Configured sources"))
        layout.addWidget(self.mail_sources)
        self.tabs.addTab(tab, "Mail Sources")

    def _build_sheets_tab(self) -> None:
        tab = QWidget()
        layout = QFormLayout(tab)
        self.sheet_id = QLineEdit()
        self.sheets_client_file = QLineEdit()
        browse = QPushButton("Browse Sheets OAuth JSON")
        browse.clicked.connect(lambda: self._browse_file(self.sheets_client_file))
        connect = QPushButton("Connect Google Sheets")
        connect.clicked.connect(self._connect_sheets)
        save = QPushButton("Save Sheets Settings")
        save.clicked.connect(self._save_sheets)
        layout.addRow("Spreadsheet ID", self.sheet_id)
        layout.addRow("OAuth client JSON", self.sheets_client_file)
        layout.addRow(browse)
        layout.addRow(connect)
        layout.addRow(save)
        self.tabs.addTab(tab, "Google Sheets")

    def _build_ai_tab(self) -> None:
        tab = QWidget()
        layout = QFormLayout(tab)
        self.ai_enabled = QCheckBox("Use AI fallback for low-confidence extraction")
        self.ai_provider = QComboBox()
        self.ai_provider.addItems(["openai", "anthropic"])
        self.ai_key = QLineEdit()
        self.ai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_model = QComboBox()
        validate = QPushButton("Save Key and Fetch Models")
        validate.clicked.connect(self._save_ai_and_fetch_models)
        save = QPushButton("Save AI Settings")
        save.clicked.connect(self._save_ai)
        layout.addRow(self.ai_enabled)
        layout.addRow("Provider", self.ai_provider)
        layout.addRow("API key", self.ai_key)
        layout.addRow("Model", self.ai_model)
        layout.addRow(validate)
        layout.addRow(save)
        self.tabs.addTab(tab, "AI Models")

    def _build_review_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.review_list = QListWidget()
        approve = QPushButton("Approve Selected")
        reject = QPushButton("Reject Selected")
        approve.clicked.connect(self._approve_selected_review)
        reject.clicked.connect(self._reject_selected_review)
        layout.addWidget(self.review_list)
        row = QHBoxLayout()
        row.addWidget(approve)
        row.addWidget(reject)
        layout.addLayout(row)
        self.tabs.addTab(tab, "Review Queue")

    def _build_logs_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        layout.addWidget(self.logs)
        self.tabs.addTab(tab, "Processing Logs")

    def _build_security_tab(self) -> None:
        tab = QWidget()
        layout = QFormLayout(tab)
        self.poll_interval = QSpinBox()
        self.poll_interval.setRange(10, 86400)
        self.start_windows = QCheckBox("Start with Windows")
        self.close_to_tray = QCheckBox("Close window to tray")
        self.allow_unscanned = QCheckBox("Development only: allow unscanned files")
        self.clamav_host = QLineEdit()
        self.clamav_port = QSpinBox()
        self.clamav_port.setRange(1, 65535)
        save = QPushButton("Save Security and Runtime Settings")
        save.clicked.connect(self._save_security)
        layout.addRow("Poll interval seconds", self.poll_interval)
        layout.addRow(self.start_windows)
        layout.addRow(self.close_to_tray)
        layout.addRow(self.allow_unscanned)
        layout.addRow("ClamAV host", self.clamav_host)
        layout.addRow("ClamAV port", self.clamav_port)
        layout.addRow(save)
        self.tabs.addTab(tab, "Security")

    def _load_config(self) -> None:
        config = self.controller.config
        self.sheet_id.setText(config.sheets.spreadsheet_id)
        self.sheets_client_file.setText(config.sheets.oauth_client_secrets_file)
        self.ai_enabled.setChecked(config.ai.fallback_enabled)
        self.ai_provider.setCurrentText(config.ai.provider)
        if config.ai.model:
            self.ai_model.addItem(config.ai.model)
            self.ai_model.setCurrentText(config.ai.model)
        self.poll_interval.setValue(config.poll_interval_seconds)
        self.start_windows.setChecked(config.start_with_windows)
        self.close_to_tray.setChecked(config.close_to_tray)
        self.allow_unscanned.setChecked(config.security.allow_unscanned_dev)
        self.clamav_host.setText(config.security.clamav_host)
        self.clamav_port.setValue(config.security.clamav_port)
        self._refresh_mail_sources()
        self._refresh_dashboard()

    def _current_config(self) -> AppConfig:
        return self.controller.config

    def _save(self, config: AppConfig) -> None:
        self.controller.save_config(config)
        self._refresh_mail_sources()
        self._refresh_dashboard()

    def _save_mail_source(self) -> None:
        config = self._current_config()
        source_id = str(uuid.uuid4())
        source = MailSourceConfig(
            id=source_id,
            kind=self.mail_kind.currentText(),
            display_name=self.mail_name.text() or self.mail_user.text() or "Mail source",
            imap_host=self.mail_host.text(),
            imap_port=self.mail_port.value(),
            imap_user=self.mail_user.text(),
            imap_mailbox=self.mailbox.text() or "INBOX",
            imap_search=self.mail_search.text() or "UNSEEN",
            gmail_client_secrets_file=self.gmail_client_file.text(),
        )
        if source.kind == "imap" and self.mail_password.text():
            self.controller.secret_store.set(imap_password_key(source_id), self.mail_password.text())
        config.mail_sources.append(source)
        self._save(config)
        self.mail_password.clear()
        self._info("Saved mail source")

    def _connect_gmail(self) -> None:
        file_name = self.gmail_client_file.text()
        if not file_name:
            self._error("Choose a Gmail OAuth client JSON file first.")
            return
        cred_name = credential_name_for_file(file_name, "gmail")
        try:
            run_oauth_flow(file_name, GMAIL_SCOPES, self.controller.secret_store, cred_name)
        except Exception as exc:
            self._error(f"Gmail OAuth failed: {exc}")
            return
        self._info("Gmail OAuth connected")

    def _save_sheets(self) -> None:
        config = self._current_config()
        config.sheets.spreadsheet_id = self.sheet_id.text().strip()
        config.sheets.oauth_client_secrets_file = self.sheets_client_file.text().strip()
        self._save(config)
        self._info("Saved Sheets settings")

    def _connect_sheets(self) -> None:
        if not self.sheets_client_file.text():
            self._error("Choose a Google OAuth client JSON file first.")
            return
        self._save_sheets()
        try:
            run_oauth_flow(self.sheets_client_file.text(), SHEETS_SCOPES, self.controller.secret_store, "sheets")
        except Exception as exc:
            self._error(f"Google Sheets OAuth failed: {exc}")
            return
        self._info("Google Sheets OAuth connected")

    def _save_ai_and_fetch_models(self) -> None:
        provider = self.ai_provider.currentText()
        key = self.ai_key.text().strip()
        if not key:
            self._error("Enter an API key first.")
            return
        self.controller.secret_store.set(ai_api_key(provider), key)
        try:
            models = AIProviderClient(provider, key).list_models()
        except AIProviderError as exc:
            self._error(str(exc))
            return
        self.ai_model.clear()
        for model in models:
            self.ai_model.addItem(model.display_name, model.id)
        self._save_ai()
        self.ai_key.clear()
        self._info(f"Fetched {len(models)} models")

    def _save_ai(self) -> None:
        config = self._current_config()
        config.ai.fallback_enabled = self.ai_enabled.isChecked()
        config.ai.provider = self.ai_provider.currentText()
        config.ai.model = self.ai_model.currentData() or self.ai_model.currentText()
        self._save(config)
        self._info("Saved AI settings")

    def _save_security(self) -> None:
        config = self._current_config()
        config.poll_interval_seconds = self.poll_interval.value()
        config.start_with_windows = self.start_windows.isChecked()
        config.close_to_tray = self.close_to_tray.isChecked()
        config.security.allow_unscanned_dev = self.allow_unscanned.isChecked()
        config.security.clamav_host = self.clamav_host.text() or "127.0.0.1"
        config.security.clamav_port = self.clamav_port.value()
        set_start_with_windows(config.start_with_windows)
        self._save(config)
        self._info("Saved runtime settings")

    def _start_scheduler(self) -> None:
        self.controller.scheduler.start()
        self._refresh_dashboard()

    def _run_once(self) -> None:
        try:
            self.controller.scheduler.run_once()
            self._refresh_review_queue()
            self._refresh_dashboard()
        except Exception as exc:
            self._error(f"{exc.__class__.__name__}: {exc}")

    def _approve_selected_review(self) -> None:
        row = self.review_list.currentRow()
        if row < 0:
            return
        task = self.controller.scheduler.review_tasks.pop(row)
        pipeline = self.controller._build_pipeline(self.controller.config)
        status = pipeline.approve_review(task, actor="desktop-reviewer")
        self._append_log(f"Approved review task {task.task_id}: {status.value}")
        self._refresh_review_queue()

    def _reject_selected_review(self) -> None:
        row = self.review_list.currentRow()
        if row < 0:
            return
        task = self.controller.scheduler.review_tasks.pop(row)
        pipeline = self.controller._build_pipeline(self.controller.config)
        pipeline.reject_review(task, reason="Rejected in desktop app", actor="desktop-reviewer")
        self._append_log(f"Rejected review task {task.task_id}")
        self._refresh_review_queue()

    def _append_event(self, event) -> None:
        self._append_log(f"{event.created_at.isoformat()} [{event.level}] {event.message}")
        self._refresh_review_queue()
        self._refresh_dashboard()

    def _refresh_dashboard(self) -> None:
        scheduler = self.controller.scheduler
        if scheduler.is_paused:
            status = "Paused"
        elif scheduler.is_running:
            status = "Running"
        else:
            status = "Stopped"
        if scheduler.last_error:
            status = f"Error: {scheduler.last_error}"
        self.status_label.setText(status)

    def _refresh_mail_sources(self) -> None:
        self.mail_sources.clear()
        for source in self.controller.config.mail_sources:
            self.mail_sources.addItem(f"{source.kind}: {source.display_name} ({'enabled' if source.enabled else 'disabled'})")

    def _refresh_review_queue(self) -> None:
        self.review_list.clear()
        for task in self.controller.scheduler.review_tasks:
            document = task.parsed_document
            self.review_list.addItem(
                f"{document.document_type.value} | {document.document_number or 'missing number'} | {document.confidence:.3f}"
            )

    def _browse_file(self, target: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose file", "", "JSON files (*.json);;All files (*.*)")
        if path:
            target.setText(path)

    def _append_log(self, text: str) -> None:
        self.logs.append(text)

    def _info(self, message: str) -> None:
        self._append_log(message)
        QMessageBox.information(self, "B2B Invoice Automation", message)

    def _error(self, message: str) -> None:
        self._append_log(message)
        QMessageBox.critical(self, "B2B Invoice Automation", message)
