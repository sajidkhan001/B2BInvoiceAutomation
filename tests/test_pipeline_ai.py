from __future__ import annotations

from b2bdoc.config import Settings
from b2bdoc.memory import BoundedMemoryManager
from b2bdoc.models import ParsedDocument, ParserProvenance, ProcessingStatus
from b2bdoc.pipeline import DocumentPipeline
from b2bdoc.security import NoOpScanner
from b2bdoc.sheets import NullLedgerWriter


class FakeParser:
    def __init__(self, confidence: float):
        self.confidence = confidence

    def parse(self, payload: bytes, *, media_type: str, filename: str | None, source_hash: str, source_locator: str):
        return ParsedDocument(
            source_hash=source_hash,
            source_locator=source_locator,
            document_number="INV-1",
            issue_date="2026-05-22",
            total="100.00",
            provenance=ParserProvenance(parser="fake", media_type=media_type),
            confidence=self.confidence,
            validation_errors=[],
        )


class FakeAIFallback:
    def __init__(self):
        self.calls = 0

    def improve(self, parsed, payload, *, media_type: str, filename: str | None):
        self.calls += 1
        improved = parsed.model_copy(deep=True)
        improved.confidence = 0.96
        improved.validation_errors = []
        return improved


def _envelope():
    settings = Settings(allow_unscanned_dev=True)
    manager = BoundedMemoryManager(settings.max_file_bytes, settings.max_inflight_bytes)
    return manager.create_envelope([b"%PDF-1.7\nai-test"], source_type="test", source_id="1", filename="a.pdf")


def test_ai_fallback_only_runs_for_low_confidence_documents():
    settings = Settings(allow_unscanned_dev=True)
    fallback = FakeAIFallback()
    writer = NullLedgerWriter()
    pipeline = DocumentPipeline(
        settings=settings,
        ledger_writer=writer,
        parser_runner=FakeParser(0.50),
        scanner=NoOpScanner(),
        ai_fallback=fallback,
    )
    result = pipeline.process(_envelope())
    assert fallback.calls == 1
    assert result.status == ProcessingStatus.autonomous


def test_ai_fallback_skips_high_confidence_documents():
    settings = Settings(allow_unscanned_dev=True)
    fallback = FakeAIFallback()
    pipeline = DocumentPipeline(
        settings=settings,
        ledger_writer=NullLedgerWriter(),
        parser_runner=FakeParser(0.95),
        scanner=NoOpScanner(),
        ai_fallback=fallback,
    )
    pipeline.process(_envelope())
    assert fallback.calls == 0
