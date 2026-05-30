from __future__ import annotations

from b2bdoc.models import ParsedDocument, ParserProvenance, ProcessingStatus, ReviewTask
from b2bdoc.pipeline import PipelineResult
from b2bdoc.worker.scheduler import AutomationScheduler


def test_scheduler_run_once_collects_review_tasks_without_binary_payload():
    document = ParsedDocument(
        source_hash="hash",
        source_locator="imap:1",
        document_number="INV-1",
        provenance=ParserProvenance(parser="test", media_type="application/pdf"),
        confidence=0.4,
    )
    task = ReviewTask(
        task_id="task1",
        parsed_document=document,
        source_locator="imap:1",
        source_hash="hash",
        reasons=["low confidence"],
    )
    scheduler = AutomationScheduler(lambda: [PipelineResult(status=ProcessingStatus.needs_review, review_task=task)])
    scheduler.run_once()
    assert scheduler.review_tasks == [task]
    assert "%PDF" not in str(scheduler.review_tasks[0].model_dump(mode="json"))


def test_scheduler_stop_terminates_background_thread():
    calls = {"count": 0}

    def poll():
        calls["count"] += 1
        return []

    scheduler = AutomationScheduler(poll, interval_seconds=1)
    scheduler.start()
    scheduler.stop()
    assert not scheduler.is_running
    assert calls["count"] >= 0
