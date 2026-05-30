from __future__ import annotations

from b2bdoc.config import Settings
from b2bdoc.memory import BoundedMemoryManager
from b2bdoc.security import SecurityViolation, sniff_media_type, validate_envelope


def test_macro_enabled_office_file_is_rejected():
    try:
        sniff_media_type("bad.xlsm", b"PK\x03\x04")
    except SecurityViolation as exc:
        assert "macro" in str(exc)
    else:
        raise AssertionError("expected macro-enabled file to be rejected")


def test_pdf_magic_is_allowed_and_sets_media_type():
    settings = Settings()
    manager = BoundedMemoryManager(settings.max_file_bytes, settings.max_inflight_bytes)
    envelope = manager.create_envelope(
        [b"%PDF-1.7\n"],
        source_type="test",
        source_id="1",
        filename="invoice.pdf",
    )
    assert validate_envelope(envelope, settings) == "application/pdf"
    assert envelope.media_type == "application/pdf"
    envelope.wipe()
