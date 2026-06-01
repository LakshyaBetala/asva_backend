"""Tests for the FastAPI control plane — auth surface only.

The full pipeline integration requires Pipecat + Sarvam + Plivo and is
covered by the live smoke test on staging, not here.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from voice_agent.server import app


@pytest.fixture(autouse=True)
def _set_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-token-xyz")


@pytest.fixture
def client():
    return TestClient(app)


def test_healthz_open(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_start_call_requires_bearer(client):
    r = client.post(
        "/agents/agt_1/calls",
        json={"to": "+919900000000", "from": "+914444444444", "lang_hint": "en-IN"},
    )
    assert r.status_code == 401


def test_start_call_rejects_bad_token(client):
    r = client.post(
        "/agents/agt_1/calls",
        headers={"authorization": "Bearer wrong"},
        json={"to": "+919900000000", "from": "+914444444444", "lang_hint": "en-IN"},
    )
    assert r.status_code == 401


def test_start_call_happy_path_returns_call_id(client):
    r = client.post(
        "/agents/agt_1/calls",
        headers={"authorization": "Bearer test-token-xyz"},
        json={
            "to": "+919900000000",
            "from": "+914444444444",
            "lang_hint": "en-IN",
            "metadata": {"lead_id": "L", "lead_first_name": "Ravi"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["call_id"].startswith("vc_")
    assert len(body["call_id"]) == 19  # "vc_" + 16 hex chars
