from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from google.auth.credentials import Credentials as GoogleCredentials
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from .config import Settings
from .models import AuditEvent, LedgerWrite, LineItem, ParsedDocument, ProcessingStatus


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TAB_HEADERS = {
    "Documents": [
        "written_at",
        "idempotency_key",
        "source_hash",
        "source_locator",
        "status",
        "document_type",
        "document_number",
        "purchase_order_number",
        "issue_date",
        "due_date",
        "supplier",
        "customer",
        "currency",
        "subtotal",
        "tax_total",
        "total",
        "confidence",
        "validation_errors",
        "actor",
    ],
    "LineItems": [
        "written_at",
        "idempotency_key",
        "source_hash",
        "line_no",
        "description",
        "quantity",
        "unit_price",
        "tax",
        "total",
        "confidence",
        "flags",
    ],
    "AuditEvents": [
        "created_at",
        "event_id",
        "source_hash",
        "source_locator",
        "event_type",
        "status",
        "confidence",
        "actor",
        "details",
    ],
    "Rejects": ["created_at", "source_hash", "source_locator", "reason", "actor"],
    "Index": ["idempotency_key", "source_hash", "written_at", "status"],
}


class LedgerWriter(Protocol):
    def write(self, ledger_write: LedgerWrite) -> ProcessingStatus:
        ...

    def reject(self, event: AuditEvent, reason: str) -> None:
        ...


def sanitize_sheet_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        text = format(value, "f")
    elif isinstance(value, (datetime,)):
        text = value.isoformat()
    elif isinstance(value, list):
        text = "; ".join(sanitize_sheet_value(item) for item in value)
    elif isinstance(value, dict):
        text = "; ".join(f"{key}={sanitize_sheet_value(item)}" for key, item in sorted(value.items()))
    else:
        text = str(value)
    if text and text[0] in {"=", "+", "-", "@"}:
        return "'" + text
    return text


def build_ledger_write(document: ParsedDocument, *, status: ProcessingStatus, actor: str) -> LedgerWrite:
    return LedgerWrite(
        idempotency_key=f"{document.source_hash}:{document.document_type.value}:{document.document_number or 'missing'}",
        document=document,
        status=status,
        actor=actor,
        audit_events=[
            AuditEvent(
                event_id=str(uuid.uuid4()),
                source_hash=document.source_hash,
                source_locator=document.source_locator,
                event_type="ledger_write_requested",
                status=status,
                confidence=document.confidence,
                actor=actor,
                details={"document_type": document.document_type.value},
            )
        ],
    )


class NullLedgerWriter:
    """In-memory writer for tests and unconfigured local UI sessions."""

    def __init__(self) -> None:
        self.writes: list[LedgerWrite] = []
        self.rejects: list[tuple[AuditEvent, str]] = []

    def write(self, ledger_write: LedgerWrite) -> ProcessingStatus:
        if any(write.idempotency_key == ledger_write.idempotency_key for write in self.writes):
            return ProcessingStatus.duplicate
        self.writes.append(ledger_write)
        return ledger_write.status

    def reject(self, event: AuditEvent, reason: str) -> None:
        self.rejects.append((event, reason))


class GoogleSheetsLedger:
    def __init__(
        self,
        spreadsheet_id: str,
        service_account_file: str | None = None,
        credentials: GoogleCredentials | None = None,
    ) -> None:
        if credentials is None:
            if service_account_file is None:
                raise ValueError("Google Sheets credentials are required")
            credentials = Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
        self.spreadsheet_id = spreadsheet_id
        self.service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        self._layout_checked = False

    @classmethod
    def from_settings(cls, settings: Settings) -> "GoogleSheetsLedger | None":
        if not settings.google_sheet_id or not settings.google_service_account_file:
            return None
        return cls(settings.google_sheet_id, settings.google_service_account_file)

    @classmethod
    def from_credentials(
        cls, spreadsheet_id: str, credentials: GoogleCredentials
    ) -> "GoogleSheetsLedger":
        return cls(spreadsheet_id, credentials=credentials)

    def ensure_layout(self) -> None:
        if self._layout_checked:
            return
        spreadsheet = self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        existing = {sheet["properties"]["title"]: sheet["properties"]["sheetId"] for sheet in spreadsheet.get("sheets", [])}
        requests = []
        for title in TAB_HEADERS:
            if title not in existing:
                properties = {"title": title}
                if title == "Index":
                    properties["hidden"] = True
                requests.append({"addSheet": {"properties": properties}})
            elif title == "Index":
                requests.append({"updateSheetProperties": {"properties": {"sheetId": existing[title], "hidden": True}, "fields": "hidden"}})
        if requests:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": requests},
            ).execute()
        for tab, headers in TAB_HEADERS.items():
            values = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"{tab}!1:1",
            ).execute().get("values", [])
            if not values:
                self._append_rows(tab, [headers])
        self._layout_checked = True

    def write(self, ledger_write: LedgerWrite) -> ProcessingStatus:
        self.ensure_layout()
        if self._idempotency_key_exists(ledger_write.idempotency_key):
            duplicate_event = AuditEvent(
                event_id=str(uuid.uuid4()),
                source_hash=ledger_write.document.source_hash,
                source_locator=ledger_write.document.source_locator,
                event_type="duplicate_suppressed",
                status=ProcessingStatus.duplicate,
                confidence=ledger_write.document.confidence,
                actor=ledger_write.actor,
            )
            self._append_rows("AuditEvents", [self._audit_row(duplicate_event)])
            return ProcessingStatus.duplicate

        now = datetime.now(timezone.utc).isoformat()
        document = ledger_write.document
        self._append_rows("Documents", [self._document_row(now, ledger_write)])
        if document.line_items:
            self._append_rows(
                "LineItems",
                [self._line_item_row(now, ledger_write.idempotency_key, document.source_hash, item) for item in document.line_items],
            )
        audit_events = ledger_write.audit_events or []
        self._append_rows("AuditEvents", [self._audit_row(event) for event in audit_events])
        self._append_rows(
            "Index",
            [[ledger_write.idempotency_key, document.source_hash, now, ledger_write.status.value]],
        )
        return ledger_write.status

    def reject(self, event: AuditEvent, reason: str) -> None:
        self.ensure_layout()
        self._append_rows(
            "Rejects",
            [[event.created_at.isoformat(), event.source_hash, event.source_locator, reason, event.actor]],
        )
        self._append_rows("AuditEvents", [self._audit_row(event)])

    def _idempotency_key_exists(self, key: str) -> bool:
        values = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range="Index!A:A",
        ).execute().get("values", [])
        return any(row and row[0] == key for row in values[1:])

    def _append_rows(self, tab: str, rows: list[list[object]]) -> None:
        safe_rows = [[sanitize_sheet_value(value) for value in row] for row in rows]
        self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": safe_rows},
        ).execute()

    def _document_row(self, written_at: str, ledger_write: LedgerWrite) -> list[object]:
        document = ledger_write.document
        return [
            written_at,
            ledger_write.idempotency_key,
            document.source_hash,
            document.source_locator,
            ledger_write.status.value,
            document.document_type.value,
            document.document_number,
            document.purchase_order_number,
            document.issue_date,
            document.due_date,
            document.supplier.name,
            document.customer.name,
            document.currency,
            document.subtotal,
            document.tax_total,
            document.total,
            document.confidence,
            document.validation_errors,
            ledger_write.actor,
        ]

    def _line_item_row(self, written_at: str, idempotency_key: str, source_hash: str, item: LineItem) -> list[object]:
        return [
            written_at,
            idempotency_key,
            source_hash,
            item.line_no,
            item.description,
            item.quantity,
            item.unit_price,
            item.tax,
            item.total,
            item.confidence,
            item.flags,
        ]

    def _audit_row(self, event: AuditEvent) -> list[object]:
        return [
            event.created_at.isoformat(),
            event.event_id,
            event.source_hash,
            event.source_locator,
            event.event_type,
            event.status.value if event.status else "",
            event.confidence,
            event.actor,
            event.details,
        ]
