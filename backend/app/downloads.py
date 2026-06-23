"""Safe HTTP responses for serving stored files (uploaded and generated).

User-uploaded bytes must never be served as inline HTML/SVG/JS on our own origin -
that would be stored XSS running with the victim's session. We serve only a small
allowlist of non-executable types inline; everything else downloads as an
attachment. Every response carries ``X-Content-Type-Options: nosniff`` so the
declared type cannot be content-sniffed toward HTML, and the filename is sanitized
so it cannot break out of the quoted Content-Disposition value.
"""
from __future__ import annotations

import re

from fastapi import Response

# Types browsers render without executing script. Deliberately EXCLUDES text/html
# and image/svg+xml (both can execute script).
_INLINE_SAFE = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "text/plain",
}


def _safe_filename(name: str) -> str:
    return re.sub(r'[\r\n"\\]', "_", name or "download").strip() or "download"


def download_response(*, data: bytes, mime: str, filename: str) -> Response:
    base = (mime or "application/octet-stream").split(";", 1)[0].strip().lower()
    if base in _INLINE_SAFE:
        disposition = "inline"
        served = "text/plain; charset=utf-8" if base == "text/plain" else base
    else:
        disposition = "attachment"
        served = "application/octet-stream"
    safe = _safe_filename(filename)
    return Response(
        content=data,
        media_type=served,
        headers={
            "Content-Disposition": f'{disposition}; filename="{safe}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
