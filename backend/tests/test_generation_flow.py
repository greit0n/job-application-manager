"""End-to-end AI flow with a fake AI backend: intake -> generate -> bundle.

Exercises the generation router together with the pdf / generation / intake / bundle
services and the storage layer, without touching the network or a real Claude.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from app.routers.generation import get_ai

from .conftest import login


class FakeAI:
    """Stands in for AIClient. Returns a fixed, realistic generation payload."""

    PAYLOAD = {
        "extracted": {
            "company": "Acme GmbH",
            "position": "Senior Engineer",
            "location": "Wien",
            "salary": "",
            "deadline": "2026-07-15",
            "requirements": ["Python", "FastAPI"],
        },
        "recommended_cv_label": "Fullstack",
        "recommended_cv_reason": "Best fit for a hands-on engineering role.",
        "motivation_letter": (
            "Sehr geehrte Damen und Herren,\n\n"
            "mit großem Interesse bewerbe ich mich. Bei Fezle habe ich Ähnliches gebaut.\n\n"
            "Mit freundlichen Grüßen\n\nMax Mustermann"
        ),
        "email_subject": "Bewerbung als Senior Engineer",
        "email_body": "Anbei meine Unterlagen. Über ein Gespräch freue ich mich.",
    }

    def complete(self, prompt, *, system=None, files=None, timeout=None):
        return "transcribed text"

    def complete_json(self, prompt, *, system=None, files=None, timeout=None):
        return dict(self.PAYLOAD)


@pytest.fixture
def ai_client(app_ctx):
    app_ctx.dependency_overrides[get_ai] = lambda: FakeAI()
    yield
    app_ctx.dependency_overrides.pop(get_ai, None)


def _fill_profile(client):
    resp = client.put(
        "/api/profile",
        json={
            "name": "Max Mustermann",
            "address": "Musterstrasse 1, 1010 Wien",
            "phone": "+43 1 234567",
            "email": "max@example.com",
        },
    )
    assert resp.status_code == 200, resp.text


def _upload_cv(client, label="Fullstack", default=True):
    resp = client.post(
        "/api/cvs",
        files={"file": (f"CV_{label}.pdf", b"%PDF-1.4 fake cv", "application/pdf")},
        data={"label": label, "language": "de", "is_default": str(default).lower()},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_full_flow(client, ai_client):
    login(client)
    _fill_profile(client)
    cv_id = _upload_cv(client)

    # Intake (paste) -> draft application
    intake = client.post(
        "/api/applications/intake",
        data={"mode": "paste", "text": "We are hiring a Senior Engineer at Acme.", "language": "de"},
    )
    assert intake.status_code == 201, intake.text
    app = intake.json()
    app_id = app["id"]
    assert app["job_text"]
    assert app["status"] == "pending"

    # Generate letter + email
    gen = client.post(
        f"/api/applications/{app_id}/generate",
        json={"language": "de", "produce_letter": True, "produce_email": True, "cv_id": None},
    )
    assert gen.status_code == 200, gen.text
    body = gen.json()
    assert "Mit freundlichen" in body["motivation_letter"]
    assert body["email_subject"] == "Bewerbung als Senior Engineer"
    assert body["email_body"]
    assert body["selected_cv_id"] == cv_id          # AI recommended "Fullstack"
    assert body["company"] == "Acme GmbH"           # backfilled from extracted
    assert body["cv_recommendation"]

    kinds = {d["kind"] for d in body["documents"]}
    assert {"motivation_letter", "email"} <= kinds

    # The rendered letter is a real PDF
    letter = next(d for d in body["documents"] if d["kind"] == "motivation_letter")
    assert letter["mime"] == "application/pdf"
    dl = client.get(f"/api/documents/{letter['id']}/download")
    assert dl.status_code == 200
    assert dl.content[:4] == b"%PDF"

    # Bundle -> zip
    bundle = client.post(f"/api/applications/{app_id}/bundle")
    assert bundle.status_code == 200, bundle.text
    zip_doc = bundle.json()
    assert zip_doc["kind"] == "zip"
    zdl = client.get(f"/api/documents/{zip_doc['id']}/download")
    assert zdl.status_code == 200
    assert zdl.content[:2] == b"PK"


def test_packet_edits_rerender_documents_and_zip(client, ai_client):
    login(client)
    _fill_profile(client)
    _upload_cv(client)

    app_id = client.post(
        "/api/applications/intake",
        data={"mode": "paste", "text": "Senior Engineer at Acme", "language": "de"},
    ).json()["id"]
    gen = client.post(
        f"/api/applications/{app_id}/generate",
        json={"language": "de", "produce_letter": True, "produce_email": True, "cv_id": None},
    )
    assert gen.status_code == 200, gen.text

    packet = client.put(
        f"/api/applications/{app_id}/packet",
        json={
            "motivation_letter": "Sehr geehrte Damen und Herren,\n\nAktualisierte Version.\n\nMit freundlichen Grüßen\n\nMax Mustermann",
            "email_subject": "Bewerbung als Senior Engineer",
            "email_body": "UPDATED EMAIL BODY",
            "language": "de",
        },
    )
    assert packet.status_code == 200, packet.text
    updated = packet.json()
    email_doc = next(d for d in updated["documents"] if d["kind"] == "email")
    email_download = client.get(f"/api/documents/{email_doc['id']}/download")
    assert email_download.status_code == 200
    assert b"UPDATED EMAIL BODY" in email_download.content

    bundle = client.post(f"/api/applications/{app_id}/bundle")
    assert bundle.status_code == 200, bundle.text
    zdl = client.get(f"/api/documents/{bundle.json()['id']}/download")
    with zipfile.ZipFile(io.BytesIO(zdl.content)) as zf:
        email_names = [name for name in zf.namelist() if name.startswith("Email_")]
        assert email_names
        assert "UPDATED EMAIL BODY" in zf.read(email_names[0]).decode("utf-8")


def test_generate_scoping(client, ai_client):
    login(client, "a@example.com", "pw-a")
    _fill_profile(client)
    app_id = client.post(
        "/api/applications/intake",
        data={"mode": "paste", "text": "hello job", "language": "en"},
    ).json()["id"]

    # User B cannot generate or bundle on A's application
    login(client, "b@example.com", "pw-b")
    assert client.post(
        f"/api/applications/{app_id}/generate",
        json={"language": "en", "produce_letter": True, "produce_email": False},
    ).status_code == 404
    assert client.post(f"/api/applications/{app_id}/bundle").status_code == 404


def test_intake_rejects_empty_paste(client, ai_client):
    login(client)
    resp = client.post("/api/applications/intake", data={"mode": "paste", "text": "   ", "language": "de"})
    assert resp.status_code == 422


def test_generate_requires_profile_for_letter(client, ai_client):
    login(client)  # fresh user, profile not filled
    app_id = client.post(
        "/api/applications/intake",
        data={"mode": "paste", "text": "Senior Engineer at Acme", "language": "de"},
    ).json()["id"]
    resp = client.post(
        f"/api/applications/{app_id}/generate",
        json={"language": "de", "produce_letter": True, "produce_email": False},
    )
    assert resp.status_code == 422
    assert "profile" in resp.json()["detail"].lower()


def test_generate_requires_a_cv_with_text(client, ai_client):
    login(client)
    _fill_profile(client)  # name + address present, but NO CV uploaded
    app_id = client.post(
        "/api/applications/intake",
        data={"mode": "paste", "text": "Senior Engineer at Acme", "language": "de"},
    ).json()["id"]
    resp = client.post(
        f"/api/applications/{app_id}/generate",
        json={"language": "de", "produce_letter": True, "produce_email": False},
    )
    assert resp.status_code == 422
    assert "cv" in resp.json()["detail"].lower()
