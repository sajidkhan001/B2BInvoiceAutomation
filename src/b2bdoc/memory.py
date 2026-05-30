from __future__ import annotations

import hashlib
import io
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable


class MemoryPolicyViolation(ValueError):
    """Raised when an incoming binary would exceed configured memory limits."""


class MemoryBuffer:
    """Single-owner mutable memory buffer for an incoming binary."""

    def __init__(self, data: bytearray, release_callback=None) -> None:
        self._data = data
        self._release_callback = release_callback
        self._wiped = False
        self._lock = threading.Lock()

    @property
    def size(self) -> int:
        return len(self._data)

    @property
    def is_wiped(self) -> bool:
        return self._wiped

    def head(self, n: int = 64) -> bytes:
        if self._wiped:
            return b""
        return bytes(self._data[:n])

    def copy_bytes(self) -> bytes:
        if self._wiped:
            raise MemoryPolicyViolation("buffer has already been wiped")
        return bytes(self._data)

    def to_file_like(self) -> io.BytesIO:
        return io.BytesIO(self.copy_bytes())

    def wipe(self) -> None:
        with self._lock:
            if self._wiped:
                return
            for index in range(len(self._data)):
                self._data[index] = 0
            self._data.clear()
            self._wiped = True
            if self._release_callback is not None:
                self._release_callback()
                self._release_callback = None

    def __repr__(self) -> str:
        return f"MemoryBuffer(size={self.size}, wiped={self._wiped})"


@dataclass(slots=True)
class IngestionEnvelope:
    source_type: str
    source_id: str
    filename: str
    claimed_content_type: str | None
    media_type: str | None
    byte_size: int
    sha256: str
    source_locator: str
    received_at: datetime
    expires_at: datetime
    buffer: MemoryBuffer = field(repr=False, compare=False)

    def __getstate__(self):
        raise TypeError("IngestionEnvelope cannot be serialized because it owns binary memory")

    def metadata_record(self) -> dict[str, str | int | None]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "filename": self.filename,
            "claimed_content_type": self.claimed_content_type,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "source_locator": self.source_locator,
            "received_at": self.received_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    def wipe(self) -> None:
        self.buffer.wipe()


class BoundedMemoryManager:
    def __init__(self, max_item_bytes: int, max_total_bytes: int) -> None:
        self.max_item_bytes = max_item_bytes
        self.max_total_bytes = max_total_bytes
        self._inflight_bytes = 0
        self._lock = threading.Lock()

    @property
    def inflight_bytes(self) -> int:
        with self._lock:
            return self._inflight_bytes

    def _reserve(self, size: int) -> None:
        if size > self.max_item_bytes:
            raise MemoryPolicyViolation(
                f"file is {size} bytes; max allowed is {self.max_item_bytes} bytes"
            )
        with self._lock:
            if self._inflight_bytes + size > self.max_total_bytes:
                raise MemoryPolicyViolation("in-flight binary memory budget exceeded")
            self._inflight_bytes += size

    def _release(self, size: int) -> None:
        with self._lock:
            self._inflight_bytes = max(0, self._inflight_bytes - size)

    def create_envelope(
        self,
        chunks: Iterable[bytes],
        *,
        source_type: str,
        source_id: str | None,
        filename: str,
        claimed_content_type: str | None = None,
        source_locator: str | None = None,
        ttl_seconds: int = 900,
    ) -> IngestionEnvelope:
        payload = bytearray()
        digest = hashlib.sha256()
        for chunk in chunks:
            if not chunk:
                continue
            next_size = len(payload) + len(chunk)
            if next_size > self.max_item_bytes:
                raise MemoryPolicyViolation(
                    f"file is larger than {self.max_item_bytes} byte item limit"
                )
            payload.extend(chunk)
            digest.update(chunk)

        size = len(payload)
        self._reserve(size)
        released = False

        def release_once() -> None:
            nonlocal released
            if not released:
                released = True
                self._release(size)

        now = datetime.now(timezone.utc)
        generated_source_id = source_id or str(uuid.uuid4())
        return IngestionEnvelope(
            source_type=source_type,
            source_id=generated_source_id,
            filename=filename,
            claimed_content_type=claimed_content_type,
            media_type=None,
            byte_size=size,
            sha256=digest.hexdigest(),
            source_locator=source_locator or f"{source_type}:{generated_source_id}:{filename}",
            received_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            buffer=MemoryBuffer(payload, release_once),
        )
