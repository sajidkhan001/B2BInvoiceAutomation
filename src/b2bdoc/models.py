from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentType(str, Enum):
    invoice = "invoice"
    credit_note = "credit_note"
    purchase_order = "purchase_order"
    delivery_note = "delivery_note"
    receipt = "receipt"
    unknown = "unknown"


class ProcessingStatus(str, Enum):
    autonomous = "autonomous"
    needs_review = "needs_review"
    rejected = "rejected"
    duplicate = "duplicate"
    approved = "approved"


class Party(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    tax_id: str | None = None
    address: str | None = None
    email: str | None = None


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_no: str | None = None
    description: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    flags: list[str] = Field(default_factory=list)


class ParserProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parser: str
    media_type: str
    page_count: int = 0
    strategies: list[str] = Field(default_factory=list)
    table_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType = DocumentType.unknown
    source_hash: str
    source_locator: str
    filename: str | None = None
    supplier: Party = Field(default_factory=Party)
    customer: Party = Field(default_factory=Party)
    document_number: str | None = None
    purchase_order_number: str | None = None
    issue_date: str | None = None
    due_date: str | None = None
    currency: str = "USD"
    subtotal: Decimal | None = None
    tax_total: Decimal | None = None
    total: Decimal | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    provenance: ParserProvenance
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    field_confidence: dict[str, float] = Field(default_factory=dict)
    confidence_breakdown: dict[str, float] = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = (value or "USD").strip().upper()
        if len(value) == 1:
            return {"$": "USD", "€": "EUR", "£": "GBP", "৳": "BDT"}.get(value, "USD")
        return value[:3]


class ReviewTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    parsed_document: ParsedDocument
    reasons: list[str] = Field(default_factory=list)
    source_locator: str
    source_hash: str
    confidence_breakdown: dict[str, float] = Field(default_factory=dict)


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_hash: str | None = None
    source_locator: str | None = None
    event_type: str
    actor: str = "system"
    status: ProcessingStatus | None = None
    confidence: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class LedgerWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str
    document: ParsedDocument
    status: ProcessingStatus
    actor: str = "system"
    audit_events: list[AuditEvent] = Field(default_factory=list)
