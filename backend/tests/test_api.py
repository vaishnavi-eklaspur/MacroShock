"""API-level tests: persistence, auth, rate limiting, custom stress (Flask test client)."""
import pytest

from app import create_app
from data.reference import DEFAULT_WEIGHTS


@pytest.fixture
def client():
    return create_app().test_client()


def test_custom_stress_prices_user_shocks(client):
    r = client.post("/api/portfolio/custom-stress-test",
                    json={"weights": DEFAULT_WEIGHTS, "shocks": {"Equity": -0.30}, "name": "T"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["scenario"]["name"] == "T"
    assert body["portfolio_drawdown"] < 0            # a -30% equity shock loses money


def test_custom_stress_rejects_unknown_factor(client):
    r = client.post("/api/portfolio/custom-stress-test",
                    json={"weights": DEFAULT_WEIGHTS, "shocks": {"Nope": -0.1}})
    assert r.status_code == 400


def test_portfolio_persistence_roundtrip(client):
    client.delete("/api/portfolios/pytest_p")        # ensure clean
    assert client.post("/api/portfolios",
                       json={"name": "pytest_p", "weights": {"SPY": 0.6, "IEF": 0.4}}).status_code == 201
    names = [p["name"] for p in client.get("/api/portfolios").get_json()["portfolios"]]
    assert "pytest_p" in names
    # upsert (no duplicate)
    client.post("/api/portfolios", json={"name": "pytest_p", "weights": {"SPY": 1.0}})
    matches = [p for p in client.get("/api/portfolios").get_json()["portfolios"] if p["name"] == "pytest_p"]
    assert len(matches) == 1 and matches[0]["weights"] == {"SPY": 1.0}
    assert client.delete("/api/portfolios/pytest_p").status_code == 200
    assert client.delete("/api/portfolios/pytest_p").status_code == 404


def test_api_key_and_rate_limit(monkeypatch):
    monkeypatch.setenv("MACROSHOCK_API_KEY", "secret")
    monkeypatch.setenv("MACROSHOCK_RATE_PER_MIN", "2")
    c = create_app().test_client()
    payload = {"weights": DEFAULT_WEIGHTS, "scenario_id": "GFC_2008"}
    assert c.post("/api/portfolio/stress-test", json=payload).status_code == 401  # no key
    hdr = {"X-API-Key": "secret"}
    codes = [c.post("/api/portfolio/stress-test", json=payload, headers=hdr).status_code for _ in range(4)]
    assert codes[:2] == [200, 200] and 429 in codes                              # limiter fires
