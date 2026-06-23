from fastapi.testclient import TestClient

from app.main import create_app


def test_health() -> None:
    client = TestClient(create_app())
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_extract_json_from_fence() -> None:
    from app.services.ai_client import extract_json

    text = 'Here you go:\n```json\n{"a": 1, "b": "x"}\n```\nDone.'
    assert extract_json(text) == {"a": 1, "b": "x"}


def test_extract_json_bare_object() -> None:
    from app.services.ai_client import extract_json

    text = 'prefix {"nested": {"k": [1,2,3]}, "ok": true} suffix'
    assert extract_json(text) == {"nested": {"k": [1, 2, 3]}, "ok": True}
