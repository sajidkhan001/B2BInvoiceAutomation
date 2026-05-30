from __future__ import annotations

import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from .config import Settings
from .models import DocumentType, LineItem, ParsedDocument, ParserProvenance, Party
from .table_fallback import TableExtractionResult, choose_best_table, reconstruct_multipage_tables

try:
    import pdfplumber
except Exception:  # pragma: no cover - dependency availability is checked at runtime
    pdfplumber = None


TEXT_PARSER_NAME = "regex-structured-v1"


def parse_binary(
    payload: bytes,
    *,
    media_type: str,
    filename: str | None,
    source_hash: str,
    source_locator: str,
    settings: Settings,
) -> ParsedDocument:
    if media_type == "application/pdf":
        return _parse_pdf(payload, filename, source_hash, source_locator, settings)
    if media_type.startswith("image/"):
        return _parse_image_placeholder(media_type, filename, source_hash, source_locator)
    return _low_confidence_document(
        media_type=media_type,
        filename=filename,
        source_hash=source_hash,
        source_locator=source_locator,
        warnings=["unsupported media type"],
    )


def _parse_pdf(
    payload: bytes,
    filename: str | None,
    source_hash: str,
    source_locator: str,
    settings: Settings,
) -> ParsedDocument:
    if pdfplumber is None:
        return _low_confidence_document(
            media_type="application/pdf",
            filename=filename,
            source_hash=source_hash,
            source_locator=source_locator,
            warnings=["pdfplumber is not installed"],
        )

    warnings: list[str] = []
    strategies: list[str] = ["pdfplumber_text"]
    page_texts: list[str] = []
    table_candidates: list[TableExtractionResult] = []
    page_count = 0

    try:
        with pdfplumber.open(io.BytesIO(payload)) as pdf:
            page_count = len(pdf.pages)
            if page_count > settings.max_pages:
                warnings.append(f"page count {page_count} exceeds max {settings.max_pages}")
                return _low_confidence_document(
                    media_type="application/pdf",
                    filename=filename,
                    source_hash=source_hash,
                    source_locator=source_locator,
                    warnings=warnings,
                    page_count=page_count,
                )

            line_tables: list[list[list[Any]]] = []
            text_tables: list[list[list[Any]]] = []
            for page in pdf.pages:
                page_texts.append(page.extract_text() or "")
                try:
                    line_tables.extend(page.extract_tables(table_settings={"vertical_strategy": "lines", "horizontal_strategy": "lines"}))
                except Exception:
                    warnings.append("line table extraction failed on one page")
                try:
                    text_tables.extend(page.extract_tables(table_settings={"vertical_strategy": "text", "horizontal_strategy": "text"}))
                except Exception:
                    warnings.append("text table extraction failed on one page")

            if line_tables:
                strategies.append("line_tables")
                table_candidates.append(reconstruct_multipage_tables(line_tables))
            if text_tables:
                strategies.append("text_tables")
                table_candidates.append(reconstruct_multipage_tables(text_tables))
    except Exception as exc:
        return _low_confidence_document(
            media_type="application/pdf",
            filename=filename,
            source_hash=source_hash,
            source_locator=source_locator,
            warnings=[f"pdf parse failed: {exc.__class__.__name__}"],
        )

    table_result = choose_best_table(table_candidates)
    text = "\n".join(page_texts)
    return parse_text_to_document(
        text,
        table_result=table_result,
        media_type="application/pdf",
        filename=filename,
        source_hash=source_hash,
        source_locator=source_locator,
        page_count=page_count,
        strategies=strategies + [table_result.strategy],
        warnings=warnings,
    )


def _parse_image_placeholder(
    media_type: str,
    filename: str | None,
    source_hash: str,
    source_locator: str,
) -> ParsedDocument:
    return _low_confidence_document(
        media_type=media_type,
        filename=filename,
        source_hash=source_hash,
        source_locator=source_locator,
        warnings=["image OCR broker is not configured"],
    )


def parse_text_to_document(
    text: str,
    *,
    table_result: TableExtractionResult,
    media_type: str,
    filename: str | None,
    source_hash: str,
    source_locator: str,
    page_count: int,
    strategies: list[str],
    warnings: list[str] | None = None,
) -> ParsedDocument:
    warnings = list(warnings or [])
    document_type = classify_document(text)
    document_number = _first_match(
        text,
        [
            r"(?i)\b(?:invoice|inv|credit\s+note|receipt|po|purchase\s+order|delivery\s+note)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\/]+)",
            r"(?i)\b(?:document)\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\/]+)",
        ],
    )
    purchase_order_number = _first_match(
        text,
        [r"(?i)\b(?:po|purchase\s+order)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\/]+)"],
    )
    issue_date = _extract_date(text, ["invoice date", "date", "issued", "receipt date"])
    due_date = _extract_date(text, ["due date", "payment due"])
    currency = _extract_currency(text)
    subtotal = _extract_amount(text, ["subtotal", "sub total", "net amount"])
    tax_total = _extract_amount(text, ["tax", "vat", "gst"])
    total = _extract_amount(text, ["grand total", "amount due", "total amount", "total"])
    supplier = Party(name=_extract_party_name(text, ["from", "supplier", "vendor"]))
    customer = Party(name=_extract_party_name(text, ["bill to", "customer", "buyer", "ship to"]))
    line_items = _line_items_from_table(table_result) or _line_items_from_text(text)

    validation_errors = _semantic_validation(
        document_type=document_type,
        document_number=document_number,
        issue_date=issue_date,
        total=total,
        line_items=line_items,
        subtotal=subtotal,
        tax_total=tax_total,
    )
    confidence_breakdown = _confidence_breakdown(
        document_type=document_type,
        document_number=document_number,
        issue_date=issue_date,
        total=total,
        supplier=supplier,
        line_items=line_items,
        table_confidence=table_result.confidence,
        validation_errors=validation_errors,
    )
    confidence = round(sum(confidence_breakdown.values()), 3)
    field_confidence = {
        "document_type": 0.9 if document_type != DocumentType.unknown else 0.2,
        "document_number": 0.85 if document_number else 0.0,
        "issue_date": 0.8 if issue_date else 0.0,
        "total": 0.85 if total is not None else 0.0,
        "line_items": table_result.confidence if line_items else 0.0,
    }

    try:
        return ParsedDocument(
            document_type=document_type,
            source_hash=source_hash,
            source_locator=source_locator,
            filename=filename,
            supplier=supplier,
            customer=customer,
            document_number=document_number,
            purchase_order_number=purchase_order_number,
            issue_date=issue_date,
            due_date=due_date,
            currency=currency,
            subtotal=subtotal,
            tax_total=tax_total,
            total=total,
            line_items=line_items,
            provenance=ParserProvenance(
                parser=TEXT_PARSER_NAME,
                media_type=media_type,
                page_count=page_count,
                strategies=strategies,
                table_confidence=table_result.confidence,
                warnings=warnings,
            ),
            confidence=confidence,
            field_confidence=field_confidence,
            confidence_breakdown=confidence_breakdown,
            validation_errors=validation_errors,
        )
    except ValidationError as exc:
        return _low_confidence_document(
            media_type=media_type,
            filename=filename,
            source_hash=source_hash,
            source_locator=source_locator,
            warnings=warnings + [f"schema validation failed: {len(exc.errors())} errors"],
            page_count=page_count,
        )


def classify_document(text: str) -> DocumentType:
    lowered = text.lower()
    if "credit note" in lowered or "credit memo" in lowered:
        return DocumentType.credit_note
    if "purchase order" in lowered or re.search(r"\bpo\s*(?:no|#|number)", lowered):
        return DocumentType.purchase_order
    if "delivery note" in lowered or "goods receipt" in lowered or "packing slip" in lowered:
        return DocumentType.delivery_note
    if "receipt" in lowered and "invoice" not in lowered:
        return DocumentType.receipt
    if "invoice" in lowered or "amount due" in lowered:
        return DocumentType.invoice
    return DocumentType.unknown


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip().strip("#:")
    return None


def _extract_date(text: str, labels: list[str]) -> str | None:
    date_pattern = r"([0-3]?\d[\/\-.][01]?\d[\/\-.](?:20)?\d{2}|(?:20)\d{2}[\/\-.][01]?\d[\/\-.][0-3]?\d|[A-Z][a-z]{2,8}\s+[0-3]?\d,\s*(?:20)?\d{2})"
    for label in labels:
        match = re.search(rf"(?i){re.escape(label)}\s*[:\-]?\s*{date_pattern}", text)
        if match:
            return _normalize_date(match.group(1))
    match = re.search(date_pattern, text)
    return _normalize_date(match.group(1)) if match else None


def _normalize_date(value: str) -> str | None:
    formats = ["%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y", "%m-%d-%Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%d/%m/%y", "%m/%d/%y"]
    cleaned = value.replace(".", "/")
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return value


def _extract_currency(text: str) -> str:
    match = re.search(r"\b(USD|EUR|GBP|BDT|AUD|CAD|INR)\b|[$€£৳]", text, re.IGNORECASE)
    if not match:
        return "USD"
    token = match.group(0).upper()
    return {"$": "USD", "€": "EUR", "£": "GBP", "৳": "BDT"}.get(token, token)


def _extract_amount(text: str, labels: list[str]) -> Decimal | None:
    amount = r"(?:USD|EUR|GBP|BDT|AUD|CAD|INR|[$€£৳])?\s*([0-9][0-9,]*(?:\.\d{1,2})?)"
    for label in labels:
        matches = list(re.finditer(rf"(?i)\b{re.escape(label)}\b\s*[:\-]?\s*{amount}", text))
        if matches:
            return _to_decimal(matches[-1].group(1))
    return None


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    cleaned = str(value).replace(",", "").replace("$", "").replace("€", "").replace("£", "").replace("৳", "").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _extract_party_name(text: str, labels: list[str]) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        lower = line.lower().rstrip(":")
        if any(lower.startswith(label) for label in labels):
            inline = line.split(":", 1)[1].strip() if ":" in line else ""
            if inline:
                return inline[:180]
            if index + 1 < len(lines):
                return lines[index + 1][:180]
    return None


def _line_items_from_table(result: TableExtractionResult) -> list[LineItem]:
    if not result.rows:
        return []
    items: list[LineItem] = []
    for index, row in enumerate(result.rows, start=1):
        cells = [cell for cell in row if cell]
        if len(cells) < 2:
            continue
        if any(word in " ".join(cells).lower() for word in ["subtotal", "grand total", "amount due"]):
            continue
        numbers = [_to_decimal(cell) for cell in cells]
        numeric_indexes = [i for i, number in enumerate(numbers) if number is not None]
        description_cells = [cell for i, cell in enumerate(cells) if i not in numeric_indexes]
        description = " ".join(description_cells).strip() or cells[0]
        quantity = numbers[numeric_indexes[0]] if numeric_indexes else None
        unit_price = numbers[numeric_indexes[1]] if len(numeric_indexes) >= 2 else None
        total = numbers[numeric_indexes[-1]] if numeric_indexes else None
        items.append(
            LineItem(
                line_no=str(index),
                description=description[:500],
                quantity=quantity,
                unit_price=unit_price,
                total=total,
                confidence=max(0.1, min(0.95, result.confidence)),
                flags=["merged_split_row"] if index - 1 in result.flagged_rows else [],
            )
        )
    return items


def _line_items_from_text(text: str) -> list[LineItem]:
    items: list[LineItem] = []
    pattern = re.compile(r"(?m)^\s*(\d+)?\s*([A-Za-z][A-Za-z0-9 .,\-]{4,}?)\s+(\d+(?:\.\d+)?)\s+([0-9,]+(?:\.\d{1,2})?)\s+([0-9,]+(?:\.\d{1,2})?)\s*$")
    for index, match in enumerate(pattern.finditer(text), start=1):
        items.append(
            LineItem(
                line_no=match.group(1) or str(index),
                description=match.group(2).strip()[:500],
                quantity=_to_decimal(match.group(3)),
                unit_price=_to_decimal(match.group(4)),
                total=_to_decimal(match.group(5)),
                confidence=0.55,
            )
        )
    return items


def _semantic_validation(
    *,
    document_type: DocumentType,
    document_number: str | None,
    issue_date: str | None,
    total: Decimal | None,
    line_items: list[LineItem],
    subtotal: Decimal | None,
    tax_total: Decimal | None,
) -> list[str]:
    errors: list[str] = []
    if document_type == DocumentType.unknown:
        errors.append("document type could not be classified")
    if not document_number:
        errors.append("document number missing")
    if not issue_date:
        errors.append("issue date missing")
    if total is None:
        errors.append("total amount missing")
    if document_type in {DocumentType.invoice, DocumentType.purchase_order, DocumentType.credit_note} and not line_items:
        errors.append("line items missing")
    if subtotal is not None and tax_total is not None and total is not None:
        if abs((subtotal + tax_total) - total) > Decimal("0.05"):
            errors.append("subtotal plus tax does not match total")
    return errors


def _confidence_breakdown(
    *,
    document_type: DocumentType,
    document_number: str | None,
    issue_date: str | None,
    total: Decimal | None,
    supplier: Party,
    line_items: list[LineItem],
    table_confidence: float,
    validation_errors: list[str],
) -> dict[str, float]:
    breakdown = {
        "base_extraction": 0.35,
        "document_type": 0.10 if document_type != DocumentType.unknown else 0.0,
        "required_fields": 0.0,
        "table_continuity": 0.0,
        "arithmetic_schema": 0.0,
        "source_quality": 0.05,
    }
    required_hits = sum(1 for value in [document_number, issue_date, total, supplier.name] if value)
    breakdown["required_fields"] = 0.25 * (required_hits / 4)
    if line_items:
        breakdown["table_continuity"] = 0.15 * max(0.25, table_confidence)
    breakdown["arithmetic_schema"] = 0.10 if not validation_errors else max(0.0, 0.10 - (0.025 * len(validation_errors)))
    return {key: round(value, 3) for key, value in breakdown.items()}


def _low_confidence_document(
    *,
    media_type: str,
    filename: str | None,
    source_hash: str,
    source_locator: str,
    warnings: list[str],
    page_count: int = 0,
) -> ParsedDocument:
    return ParsedDocument(
        document_type=DocumentType.unknown,
        source_hash=source_hash,
        source_locator=source_locator,
        filename=filename,
        provenance=ParserProvenance(
            parser=TEXT_PARSER_NAME,
            media_type=media_type,
            page_count=page_count,
            strategies=["low_confidence_fallback"],
            table_confidence=0.0,
            warnings=warnings,
        ),
        confidence=0.05,
        confidence_breakdown={"base_extraction": 0.05},
        validation_errors=warnings or ["document could not be parsed"],
    )
