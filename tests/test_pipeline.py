from __future__ import annotations

import builtins

import pytest

from b2bdoc.config import Settings
from b2bdoc.memory import BoundedMemoryManager
from b2bdoc.models import ParsedDocument, ParserProvenance, ProcessingStatus
from b2bdoc.pipeline import DocumentPipeline
from b2bdoc.security import NoOpScanner
from b2bdoc.sheets import NullLedgerWriter


class FakeParser:
    def __init__(self, confidence: float, errors: list[str] | None = None) -> None:
        self.confidence = confidence
        self.errors = errors or []

    def parse(self, payload: bytes, *, media_type: str, filename: str | None, source_hash: str, source_locator: str):
        assert payload.startswith(b"%PDF")
        return ParsedDocument(
            source_hash=source_hash,
            source_locator=source_locator,
            filename=filename,
            document_number="INV-100",
            issue_date="2026-05-22",
            total="100.00",
            provenance=ParserProvenance(parser="fake", media_type=media_type),
            confidence=self.confidence,
            validation_errors=self.errors,
        )


def _envelope():
    settings = Settings(allow_unscanned_dev=True)
    manager = BoundedMemoryManager(settings.max_file_bytes, settings.max_inflight_bytes)
    return manager.create_envelope(
        [b"%PDF-1.7\nbinary-secret-marker"],
        source_type="test",
        source_id="1",
        filename="invoice.pdf",
    )


def test_pipeline_routes_high_confidence_to_ledger_and_wipes_binary():
    settings = Settings(allow_unscanned_dev=True)
    writer = NullLedgerWriter()
    pipeline = DocumentPipeline(
        settings=settings,
        ledger_writer=writer,
        parser_runner=FakeParser(confidence=0.95),
        scanner=NoOpScanner(),
    )
    envelope = _envelope()
    result = pipeline.process(envelope)
    assert result.status == ProcessingStatus.autonomous
    assert len(writer.writes) == 1
    assert envelope.buffer.is_wiped


def test_pipeline_routes_low_confidence_to_review_without_binary_payload():
    settings = Settings(allow_unscanned_dev=True)
    writer = NullLedgerWriter()
    pipeline = DocumentPipeline(
        settings=settings,
        ledger_writer=writer,
        parser_runner=FakeParser(confidence=0.40, errors=["total amount missing"]),
        scanner=NoOpScanner(),
    )
    result = pipeline.process(_envelope())
    assert result.status == ProcessingStatus.needs_review
    dumped = str(result.review_task.model_dump(mode="json"))
    assert "%PDF" not in dumped
    assert "binary-secret-marker" not in dumped


def test_pipeline_does_not_write_binary_files(monkeypatch):
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+", "b")):
            raise AssertionError(f"unexpected file write/open mode: {mode}")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    settings = Settings(allow_unscanned_dev=True)
    pipeline = DocumentPipeline(
        settings=settings,
        ledger_writer=NullLedgerWriter(),
        parser_runner=FakeParser(confidence=0.95),
        scanner=NoOpScanner(),
    )
    result = pipeline.process(_envelope())
    assert result.status == ProcessingStatus.autonomous
