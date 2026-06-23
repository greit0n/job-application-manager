"""Job-posting intake: turn a paste/URL/uploaded-file into normalized job text.

Pure module - standard library + pdfplumber + httpx + bs4. No FastAPI, no DB.
The AI backend is passed in as ``ai`` (an object exposing ``complete(...)``); this
module never imports the AIClient class.
"""

from __future__ import annotations

import io
import ipaddress
import os
import re
import socket
import tempfile
from urllib.parse import urlsplit

import httpx
import pdfplumber
from bs4 import BeautifulSoup

__all__ = [
    "IntakeError",
    "normalize",
    "extract_pdf_text",
    "extract_url_text",
    "extract_image_text",
    "intake",
]

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Tags that never carry the posting body.
_DROP_TAGS = ("script", "style", "nav", "footer", "header", "aside")

# SSRF defense: the URL-intake feature fetches a user-supplied URL server-side, and
# this service runs on a shared host next to other projects, the host Postgres
# cluster, and (on cloud hosts) link-local metadata endpoints. We only allow
# http/https to public, externally-routable addresses.
_MAX_REDIRECTS = 5
_BLOCKED_HOSTNAMES = {
    "metadata.google.internal",
    "metadata.aws.internal",
    "metadata.azure.internal",
    "metadata",
}


class IntakeError(RuntimeError):
    """Raised when a job posting cannot be turned into usable text."""


def _ip_is_blocked(ip_text: str) -> bool:
    """True for any non-public address (loopback/private/link-local/etc.)."""
    try:
        addr = ipaddress.ip_address(ip_text)
    except ValueError:
        return True  # unparseable -> refuse
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _assert_public_url(url: str) -> None:
    """Reject non-http(s), credentialed, metadata, or private/internal URLs.

    Resolves the hostname and refuses if ANY resolved address is non-public. Note:
    a small DNS-rebinding window remains (httpx re-resolves on connect); this guard
    blocks the common SSRF targets and is re-applied on every redirect hop.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise IntakeError("Only http and https URLs can be fetched.")
    if parts.username or parts.password:
        raise IntakeError("URLs that embed credentials are not allowed.")
    host = parts.hostname
    if not host:
        raise IntakeError("The URL has no host.")
    if host.lower() in _BLOCKED_HOSTNAMES:
        raise IntakeError("That host is not allowed.")

    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise IntakeError(f"Could not resolve the host ({exc}).") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise IntakeError("Could not resolve the host.")
    if any(_ip_is_blocked(ip) for ip in addresses):
        raise IntakeError(
            "That URL resolves to a private or internal address and cannot be fetched."
        )


def normalize(text: str) -> str:
    """Strip, collapse 3+ blank lines to 2, trim trailing spaces per line."""
    if not text:
        return ""
    # Normalize line endings.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Trim trailing whitespace per line.
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    # Collapse 3+ consecutive newlines (2+ blank lines) down to 2 newlines.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf_text(data: bytes) -> str:
    """Extract text from a PDF using pdfplumber.

    Concatenate page texts with blank lines. Return normalize()'d text. Raise
    IntakeError with a clear message if extraction fails or yields nothing.
    """
    if not data:
        raise IntakeError("Empty PDF: no bytes to extract text from.")
    try:
        parts: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    parts.append(page_text)
    except IntakeError:
        raise
    except Exception as exc:  # pdfplumber / pdfminer raise a variety of errors
        raise IntakeError(f"Could not read the PDF: {exc}") from exc

    combined = "\n\n".join(parts)
    result = normalize(combined)
    if not result:
        raise IntakeError(
            "No text could be extracted from the PDF (it may be a scanned image). "
            "Try uploading it as an image or pasting the text instead."
        )
    return result


def extract_url_text(url: str, *, timeout: int = 20) -> str:
    """GET the URL and extract the posting body as normalized text.

    Raise IntakeError on network/HTTP error or empty result.
    """
    if not url or not url.strip():
        raise IntakeError("No URL provided.")
    url = url.strip()

    headers = {"User-Agent": _USER_AGENT}
    current = url
    try:
        with httpx.Client(
            follow_redirects=False, timeout=timeout, headers=headers
        ) as client:
            response = None
            for _ in range(_MAX_REDIRECTS + 1):
                _assert_public_url(current)  # validate every hop before connecting
                response = client.get(current)
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        break
                    current = str(response.url.join(location))
                    continue
                break
            else:
                raise IntakeError("Too many redirects while fetching the URL.")
            response.raise_for_status()
            html = response.text
    except IntakeError:
        raise
    except httpx.HTTPStatusError as exc:
        raise IntakeError(
            f"The page returned HTTP {exc.response.status_code}. Many job boards block "
            "automated access - try pasting the posting text instead."
        ) from exc
    except httpx.HTTPError as exc:
        raise IntakeError(
            f"Could not fetch the URL ({exc}). Many job boards block automated access - "
            "try pasting the posting text instead."
        ) from exc

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:
        raise IntakeError(f"Could not parse the page: {exc}") from exc

    # Remove tags that never hold the posting body.
    for tag in soup(list(_DROP_TAGS)):
        tag.decompose()

    container = soup.find("main") or soup.find("article") or soup.body or soup
    raw_text = container.get_text(separator="\n")

    # Collapse runs of whitespace within each line, drop empty lines.
    lines = []
    for line in raw_text.splitlines():
        collapsed = re.sub(r"[ \t\f\v]+", " ", line).strip()
        if collapsed:
            lines.append(collapsed)
    result = normalize("\n".join(lines))

    if not result:
        raise IntakeError(
            "No readable text was found at that URL. Many job boards block automated "
            "access or render content with JavaScript - try pasting the posting text "
            "instead."
        )
    return result


def extract_image_text(
    data: bytes, filename: str, ai, *, timeout: int | None = None
) -> str:
    """Transcribe a job posting from a screenshot/photo via the AI backend.

    Write bytes to a temp file (keeping the original extension), call the model to
    transcribe, clean up, and return normalize()'d text. Raise IntakeError if ai is
    None or it raises.
    """
    if ai is None:
        raise IntakeError("No AI backend available to transcribe the image.")
    if not data:
        raise IntakeError("Empty image: no bytes to transcribe.")

    ext = os.path.splitext(filename or "")[1]
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=ext)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
        except Exception:
            # fdopen failed before taking ownership of the descriptor.
            try:
                os.close(fd)
            except OSError:
                pass
            raise

        try:
            basename = os.path.basename(tmp_path)
            transcription = ai.complete(
                f"Read the image file '{basename}' in the current directory and "
                "transcribe ALL of its text verbatim as plain text. It is a job "
                "posting. Output only the transcription, nothing else.",
                files=[os.path.abspath(tmp_path)],
                timeout=timeout,
            )
        except Exception as exc:
            raise IntakeError(f"Image transcription failed: {exc}") from exc
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    result = normalize(transcription or "")
    if not result:
        raise IntakeError(
            "The image could not be transcribed (no text returned). Try pasting the "
            "posting text instead."
        )
    return result


def intake(
    *,
    mode: str,
    text: str = "",
    url: str = "",
    file_bytes: bytes | None = None,
    filename: str = "",
    content_type: str = "",
    ai=None,
    timeout: int | None = None,
) -> str:
    """Dispatch to the right extractor and return normalized job text."""
    if mode == "paste":
        result = normalize(text)
        if not result:
            raise IntakeError("No text was pasted.")
        return result

    if mode == "url":
        if timeout is None:
            return extract_url_text(url)
        return extract_url_text(url, timeout=timeout)

    if mode == "upload":
        if not file_bytes:
            raise IntakeError("No file was uploaded.")
        ctype = (content_type or "").lower()
        fname = (filename or "").lower()
        is_pdf = ctype == "application/pdf" or fname.endswith(".pdf")
        if is_pdf:
            return extract_pdf_text(file_bytes)
        if ctype.startswith("image/"):
            return extract_image_text(file_bytes, filename, ai, timeout=timeout)
        raise IntakeError(
            f"Unsupported upload type (content_type={content_type!r}, "
            f"filename={filename!r}). Upload a PDF or an image, or paste the text."
        )

    raise IntakeError(f"Unknown intake mode: {mode!r}.")
