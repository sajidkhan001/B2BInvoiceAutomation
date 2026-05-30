from __future__ import annotations

import email
import imaplib
from email.message import EmailMessage
from email.policy import default
from typing import Iterable

from .config import Settings
from .memory import BoundedMemoryManager, IngestionEnvelope
from .pipeline import DocumentPipeline, PipelineResult


def iter_attachment_envelopes(
    message: EmailMessage,
    *,
    uid: str,
    memory: BoundedMemoryManager,
) -> Iterable[IngestionEnvelope]:
    attachment_index = 0
    for part in message.iter_attachments():
        filename = part.get_filename() or f"attachment-{attachment_index}"
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        attachment_index += 1
        locator = f"imap:{uid}:part:{attachment_index}:{filename}"
        yield memory.create_envelope(
            [payload],
            source_type="imap",
            source_id=uid,
            filename=filename,
            claimed_content_type=part.get_content_type(),
            source_locator=locator,
        )


class IMAPIngestor:
    def __init__(self, settings: Settings, memory: BoundedMemoryManager, pipeline: DocumentPipeline) -> None:
        if not settings.imap_host or not settings.imap_user or not settings.imap_password:
            raise ValueError("IMAP settings are incomplete")
        self.settings = settings
        self.memory = memory
        self.pipeline = pipeline

    def run_once(self) -> list[PipelineResult]:
        results: list[PipelineResult] = []
        with imaplib.IMAP4_SSL(self.settings.imap_host, self.settings.imap_port) as client:
            client.login(self.settings.imap_user, self.settings.imap_password)
            client.select(self.settings.imap_mailbox)
            status, data = client.uid("search", None, self.settings.imap_search)
            if status != "OK":
                raise RuntimeError("IMAP search failed")
            for uid_bytes in data[0].split():
                uid = uid_bytes.decode("ascii", errors="replace")
                status, fetched = client.uid("fetch", uid, "(RFC822)")
                if status != "OK":
                    continue
                message_bytes = _extract_message_bytes(fetched)
                if not message_bytes:
                    continue
                message = email.message_from_bytes(message_bytes, policy=default)
                for envelope in iter_attachment_envelopes(message, uid=uid, memory=self.memory):
                    results.append(self.pipeline.process(envelope, actor="imap"))
        return results


def _extract_message_bytes(fetched: list[object]) -> bytes | None:
    for item in fetched:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None
