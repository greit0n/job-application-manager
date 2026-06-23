"""Downloads must never serve user-uploaded HTML/SVG inline on our origin (XSS),
and must always send X-Content-Type-Options: nosniff."""
from __future__ import annotations

from .conftest import login


def _make_app(client) -> int:
    return client.post(
        "/api/applications",
        json={"company": "Acme", "position": "Eng", "language": "de"},
    ).json()["id"]


def test_html_upload_is_served_as_attachment_octet_stream(client):
    login(client)
    app_id = _make_app(client)
    up = client.post(
        f"/api/applications/{app_id}/documents",
        files={"file": ("evil.html", b"<script>alert(document.cookie)</script>", "text/html")},
        data={"kind": "proof"},
    )
    assert up.status_code == 201, up.text
    doc_id = up.json()["id"]

    dl = client.get(f"/api/documents/{doc_id}/download")
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith("application/octet-stream")
    assert "attachment" in dl.headers["content-disposition"].lower()
    assert dl.headers["x-content-type-options"] == "nosniff"


def test_svg_upload_is_not_inline(client):
    login(client)
    app_id = _make_app(client)
    up = client.post(
        f"/api/applications/{app_id}/documents",
        files={"file": ("x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", "image/svg+xml")},
        data={"kind": "proof"},
    )
    doc_id = up.json()["id"]
    dl = client.get(f"/api/documents/{doc_id}/download")
    assert "attachment" in dl.headers["content-disposition"].lower()
    assert dl.headers["x-content-type-options"] == "nosniff"


def test_pdf_upload_stays_inline(client):
    login(client)
    app_id = _make_app(client)
    up = client.post(
        f"/api/applications/{app_id}/documents",
        files={"file": ("posting.pdf", b"%PDF-1.4 ok", "application/pdf")},
        data={"kind": "posting"},
    )
    doc_id = up.json()["id"]
    dl = client.get(f"/api/documents/{doc_id}/download")
    assert dl.headers["content-type"].startswith("application/pdf")
    assert "inline" in dl.headers["content-disposition"].lower()
    assert dl.headers["x-content-type-options"] == "nosniff"


def test_filename_quote_is_sanitized_in_header(client):
    login(client)
    app_id = _make_app(client)
    up = client.post(
        f"/api/applications/{app_id}/documents",
        files={"file": ('a".pdf', b"%PDF-1.4 ok", "application/pdf")},
        data={"kind": "posting"},
    )
    doc_id = up.json()["id"]
    dl = client.get(f"/api/documents/{doc_id}/download")
    cd = dl.headers["content-disposition"]
    # The raw double-quote must not survive into the header value.
    assert cd.count('"') == 2  # only the two wrapping quotes
