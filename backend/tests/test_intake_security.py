"""SSRF guard for the URL-intake feature (offline: all cases reject pre-connect)."""
from __future__ import annotations

import pytest

from app.services.intake import IntakeError, extract_url_text


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:5433/",
        "http://169.254.169.254/latest/meta-data/",   # cloud metadata (link-local)
        "http://10.0.0.5/",                            # private
        "http://192.168.1.1/",                         # private
        "http://[::1]/",                               # loopback v6
        "http://metadata.google.internal/",            # denylisted host
        "http://0.0.0.0/",                             # unspecified
        "file:///etc/passwd",                          # non-http scheme
        "ftp://example.com/x",                         # non-http scheme
        "http://user:pass@example.com/",               # embedded credentials
    ],
)
def test_url_intake_rejects_internal_and_unsafe(url):
    with pytest.raises(IntakeError):
        extract_url_text(url, timeout=2)
