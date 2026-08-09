"""Validated transfer options shared by the download dialog, queue, and worker."""

from __future__ import annotations

from dataclasses import dataclass
import string


MIN_PARTS = 1
MAX_PARTS = 32


def parse_checksum(value: str) -> tuple[str, str] | None:
    """Return a normalized supported checksum, or raise ``ValueError``.

    An omitted checksum is represented by ``None``. Barq currently supports
    MD5 and SHA-256 because those are the algorithms exposed by the dialog.
    """
    normalized = value.strip().lower()
    if not normalized:
        return None
    if any(character not in string.hexdigits for character in normalized):
        raise ValueError("Checksum must contain hexadecimal characters only")
    if len(normalized) == 32:
        return ("md5", normalized)
    if len(normalized) == 64:
        return ("sha256", normalized)
    raise ValueError("Checksum must be a 32-character MD5 or 64-character SHA-256 value")


@dataclass(frozen=True)
class DownloadOptions:
    """Per-task choices that affect the Python transfer worker."""

    parts: int | None = None
    checksum: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        if self.parts is not None and not MIN_PARTS <= self.parts <= MAX_PARTS:
            raise ValueError(f"parts must be between {MIN_PARTS} and {MAX_PARTS}")
