from __future__ import annotations

import concurrent.futures
import uuid
from dataclasses import dataclass
from typing import Protocol

from .config import Settings
from .memory import IngestionEnvelope
from .models import AuditEvent, ParsedDocument, ProcessingStatus, ReviewTask
from .parser import parse_binary
from .security import ClamAVScanner, ScanResult, SecurityViolation, validate_envelope
from .sheets import LedgerWriter, build_ledger_write


class ParserRunner(Protocol):
    def parse(
        self,
        payload: bytes,
        *,
        media_type: str,
        filename: str | None,
        source_hash: str,
        source_locator: str,
    ) -> ParsedDocument:
        ...


class AIFallback(Protocol):
    def improve(
        self,
        parsed: ParsedDocument,
        payload: bytes,
        *,
        media_type: str,
        filename: str | None,
    ) -> ParsedDocument | None:
        ...


class InlineParserRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def parse(
        self,
        payload: bytes,
        *,
        media_type: str,
        filename: str | None,
        source_hash: str,
        source_locator: str,
    ) -> ParsedDocument:
        return parse_binary(
            payload,
            media_type=media_type,
            filename=filename,
            source_hash=source_hash,
            source_locator=source_locator,
            settings=self.settings,
        )


def _parse_worker(
    payload: bytes,
    media_type: str,
    filename: str | None,
    source_hash: str,
    source_locator: str,
    settings: Settings,
) -> ParsedDocument:
    return parse_binary(
        payload,
        media_type=media_type,
        filename=filename,
        source_hash=source_hash,
        source_locator=source_locator,
        settings=settings,
    )


class ProcessParserRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def parse(
        self,
        payload: bytes,
        *,
        media_type: str,
        filename: str | None,
        source_hash: str,
        source_locator: str,
    ) -> ParsedDocument:
        with concurrent.futures.ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                _parse_worker,
                payload,
                media_type,
                filename,
                source_hash,
                source_locator,
                self.settings,
            )
            return future.result(timeout=self.settings.parser_timeout_seconds)


@dataclass(frozen=True, slots=True)
class PipelineResult:
    status: ProcessingStatus
    parsed_document: ParsedDocument | None = None
    review_task: ReviewTask | None = None
    audit_event: AuditEvent | None = None
    scan_result: ScanResult | None = None
    reason: str | None = None


class DocumentPipeline:
    def __init__(
        self,
        *,
        settings: Settings,
        ledger_writer: LedgerWriter,
        parser_runner: ParserRunner | None = None,
        scanner=None,
        ai_fallback: AIFallback | None = None,
    ) -> None:
        self.settings = settings
        self.ledger_writer = ledger_writer
        self.parser_runner = parser_runner or ProcessParserRunner(settings)
        self.scanner = scanner or ClamAVScanner(settings)
        self.ai_fallback = ai_fallback

    def process(self, envelope: IngestionEnvelope, *, actor: str = "system") -> PipelineResult:
        try:
            media_type = validate_envelope(envelope, self.settings)
            scan_result = self.scanner.scan(envelope.buffer)
            if not scan_result.clean:
                event = self._audit_event(
                    envelope,
                    "attachment_rejected",
                    actor=actor,
                    status=ProcessingStatus.rejected,
                    details={"reason": "malware scan failed", "verdict": scan_result.verdict},
                )
                self.ledger_writer.reject(event, f"malware scan failed: {scan_result.verdict}")
                return PipelineResult(
                    status=ProcessingStatus.rejected,
                    audit_event=event,
                    scan_result=scan_result,
                    reason="malware scan failed",
                )

            payload = envelope.buffer.copy_bytes()
            parsed = self.parser_runner.parse(
                payload,
                media_type=media_type,
                filename=envelope.filename,
                source_hash=envelope.sha256,
                source_locator=envelope.source_locator,
            )
            if self.ai_fallback and (
                parsed.confidence < self.settings.confidence_threshold
                or media_type.startswith("image/")
                or parsed.validation_errors
            ):
                improved = self.ai_fallback.improve(
                    parsed,
                    payload,
                    media_type=media_type,
                    filename=envelope.filename,
                )
                if improved and improved.confidence > parsed.confidence:
                    parsed = improved
            del payload

            if parsed.confidence >= self.settings.confidence_threshold and not parsed.validation_errors:
                ledger_write = build_ledger_write(parsed, status=ProcessingStatus.autonomous, actor=actor)
                status = self.ledger_writer.write(ledger_write)
                return PipelineResult(status=status, parsed_document=parsed, scan_result=scan_result)

            review_task = ReviewTask(
                task_id=str(uuid.uuid4()),
                parsed_document=parsed,
                reasons=parsed.validation_errors or ["confidence below autonomous threshold"],
                source_locator=parsed.source_locator,
                source_hash=parsed.source_hash,
                confidence_breakdown=parsed.confidence_breakdown,
            )
            return PipelineResult(
                status=ProcessingStatus.needs_review,
                parsed_document=parsed,
                review_task=review_task,
                scan_result=scan_result,
                reason="confidence below threshold or validation errors present",
            )
        except (SecurityViolation, ValueError) as exc:
            event = self._audit_event(
                envelope,
                "attachment_rejected",
                actor=actor,
                status=ProcessingStatus.rejected,
                details={"reason": exc.__class__.__name__},
            )
            self.ledger_writer.reject(event, str(exc))
            return PipelineResult(status=ProcessingStatus.rejected, audit_event=event, reason=str(exc))
        finally:
            envelope.wipe()

    def approve_review(self, review_task: ReviewTask, *, actor: str = "reviewer") -> ProcessingStatus:
        ledger_write = build_ledger_write(review_task.parsed_document, status=ProcessingStatus.approved, actor=actor)
        return self.ledger_writer.write(ledger_write)

    def reject_review(self, review_task: ReviewTask, *, reason: str, actor: str = "reviewer") -> None:
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            source_hash=review_task.source_hash,
            source_locator=review_task.source_locator,
            event_type="review_rejected",
            status=ProcessingStatus.rejected,
            confidence=review_task.parsed_document.confidence,
            actor=actor,
            details={"reason": reason},
        )
        self.ledger_writer.reject(event, reason)

    def _audit_event(
        self,
        envelope: IngestionEnvelope,
        event_type: str,
        *,
        actor: str,
        status: ProcessingStatus,
        details: dict[str, object],
    ) -> AuditEvent:
        return AuditEvent(
            event_id=str(uuid.uuid4()),
            source_hash=envelope.sha256,
            source_locator=envelope.source_locator,
            event_type=event_type,
            actor=actor,
            status=status,
            details=details,
        )
