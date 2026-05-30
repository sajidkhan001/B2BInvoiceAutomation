from __future__ import annotations

from decimal import Decimal

from b2bdoc.models import ParsedDocument, ParserProvenance, ProcessingStatus
from b2bdoc.sheets import NullLedgerWriter, build_ledger_write, sanitize_sheet_value


def test_sanitize_sheet_value_blocks_formula_injection():
    assert sanitize_sheet_value("=IMPORTXML(\"http://x\")").startswith("'=")
    assert sanitize_sheet_value("+SUM(1,2)").startswith("'+")
    assert sanitize_sheet_value("-10").startswith("'-")
    assert sanitize_sheet_value("@cmd").startswith("'@")
    assert sanitize_sheet_value(Decimal("10.50")) == "10.50"


def test_null_ledger_suppresses_duplicate_idempotency_key():
    doc = ParsedDocument(
        source_hash="abc",
        source_locator="test:abc",
        document_number="INV-1",
        provenance=ParserProvenance(parser="test", media_type="application/pdf"),
        confidence=1.0,
    )
    writer = NullLedgerWriter()
    write = build_ledger_write(doc, status=ProcessingStatus.autonomous, actor="test")
    assert writer.write(write) == ProcessingStatus.autonomous
    assert writer.write(write) == ProcessingStatus.duplicate
