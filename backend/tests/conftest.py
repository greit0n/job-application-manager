from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.auth import hash_password
from app.db import Base, get_db
from app.main import create_app


@pytest.fixture
def app_ctx():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with TestingSession() as db:
        db.add(models.User(email="a@example.com", password_hash=hash_password("pw-a"), display_name="A"))
        db.add(models.User(email="b@example.com", password_hash=hash_password("pw-b"), display_name="B"))
        db.commit()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def client(app_ctx) -> TestClient:
    return TestClient(app_ctx)


def login(client: TestClient, email: str = "a@example.com", password: str = "pw-a") -> None:
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
