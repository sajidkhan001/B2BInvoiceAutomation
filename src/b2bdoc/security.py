from __future__ import annotations

import socket
import struct
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .memory import IngestionEnvelope, MemoryBuffer, MemoryPolicyViolation


class SecurityViolation(ValueError):
    """Raised when an incoming attachment violates policy."""


@dataclass(frozen=True, slots=True)
class ScanResult:
    clean: bool
    scanner: str
    verdict: str


DANGEROUS_EXTENSIONS = {
    ".exe",
    ".dll",
    ".bat",
    ".cmd",
    ".com",
    ".js",
    ".vbs",
    ".ps1",
    ".zip",
    ".7z",
    ".rar",
    ".tar",
    ".gz",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".docm",
    ".xlsm",
    ".pptm",
}

MACRO_EXTENSIONS = {".docm", ".xlsm", ".pptm"}


def sniff_media_type(filename: str, header: bytes, *, allow_heic: bool = False) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in MACRO_EXTENSIONS:
        raise SecurityViolation("macro-enabled Office attachments are rejected")
    if suffix in DANGEROUS_EXTENSIONS:
        raise SecurityViolation(f"attachment extension {suffix} is not allowed")

    if header.startswith(b"%PDF"):
        return "application/pdf"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if allow_heic and len(header) >= 12 and header[4:8] == b"ftyp" and header[8:12] in {
        b"heic",
        b"heix",
        b"hevc",
        b"hevx",
    }:
        return "image/heic"

    raise SecurityViolation("attachment magic bytes do not match an allowed document type")


def validate_envelope(envelope: IngestionEnvelope, settings: Settings) -> str:
    if envelope.byte_size <= 0:
        raise MemoryPolicyViolation("empty attachments are not accepted")
    if envelope.byte_size > settings.max_file_bytes:
        raise MemoryPolicyViolation("attachment exceeds configured file limit")
    media_type = sniff_media_type(
        envelope.filename,
        envelope.buffer.head(64),
        allow_heic=settings.allow_heic,
    )
    envelope.media_type = media_type
    return media_type


class ClamAVScanner:
    """clamd INSTREAM scanner. Defaults to fail-closed when clamd is unavailable."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def scan(self, buffer: MemoryBuffer) -> ScanResult:
        if self.settings.allow_unscanned_dev:
            return ScanResult(clean=True, scanner="clamd-dev-bypass", verdict="UNSCANNED_DEV_BYPASS")

        try:
            with socket.create_connection(
                (self.settings.clamav_host, self.settings.clamav_port),
                timeout=self.settings.clamav_timeout_seconds,
            ) as sock:
                sock.settimeout(self.settings.clamav_timeout_seconds)
                sock.sendall(b"zINSTREAM\0")
                data = buffer.copy_bytes()
                for offset in range(0, len(data), 1024 * 1024):
                    chunk = data[offset : offset + 1024 * 1024]
                    sock.sendall(struct.pack("!I", len(chunk)))
                    sock.sendall(chunk)
                sock.sendall(struct.pack("!I", 0))
                verdict = sock.recv(4096).decode("utf-8", errors="replace").strip()
        except OSError as exc:
            return ScanResult(clean=False, scanner="clamd", verdict=f"SCANNER_UNAVAILABLE:{exc.__class__.__name__}")

        clean = verdict.endswith("OK") or " OK" in verdict
        return ScanResult(clean=clean, scanner="clamd", verdict=verdict or "NO_VERDICT")


class NoOpScanner:
    """Test-only scanner."""

    def scan(self, buffer: MemoryBuffer) -> ScanResult:
        return ScanResult(clean=True, scanner="noop", verdict="OK")
