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


def test_persistence_is_disabled_without_a_key(client):
    # Fail-closed: with no MACROSHOCK_API_KEY, writes are refused, not open.
    assert client.post("/api/portfolios",
                       json={"name": "x", "weights": {"SPY": 1.0}}).status_code == 403
    assert client.delete("/api/portfolios/x").status_code == 403
    assert client.get("/api/portfolios").status_code == 200          # reads stay open


def test_portfolio_persistence_roundtrip(monkeypatch):
    monkeypatch.setenv("MACROSHOCK_API_KEY", "k")
    c = create_app().test_client()
    hdr = {"X-API-Key": "k"}
    assert c.post("/api/portfolios", json={"name": "x", "weights": {"SPY": 1}}).status_code == 401  # no key
    c.delete("/api/portfolios/pytest_p", headers=hdr)                 # ensure clean
    assert c.post("/api/portfolios", headers=hdr,
                  json={"name": "pytest_p", "weights": {"SPY": 0.6, "IEF": 0.4}}).status_code == 201
    names = [p["name"] for p in c.get("/api/portfolios").get_json()["portfolios"]]
    assert "pytest_p" in names
    c.post("/api/portfolios", headers=hdr, json={"name": "pytest_p", "weights": {"SPY": 1.0}})  # upsert
    matches = [p for p in c.get("/api/portfolios").get_json()["portfolios"] if p["name"] == "pytest_p"]
    assert len(matches) == 1 and matches[0]["weights"] == {"SPY": 1.0}
    assert c.delete("/api/portfolios/pytest_p", headers=hdr).status_code == 200
    assert c.delete("/api/portfolios/pytest_p", headers=hdr).status_code == 404


def test_save_rejects_overlong_name(monkeypatch):
    monkeypatch.setenv("MACROSHOCK_API_KEY", "k")
    c = create_app().test_client()
    r = c.post("/api/portfolios", headers={"X-API-Key": "k"},
               json={"name": "z" * 101, "weights": {"SPY": 1.0}})
    assert r.status_code == 400


def test_compute_endpoints_stay_open_and_rate_limit(monkeypatch):
    # Compute is open (public demo needs it) even when a key is configured; only the rate
    # limiter guards it.
    monkeypatch.setenv("MACROSHOCK_API_KEY", "secret")
    monkeypatch.setenv("MACROSHOCK_RATE_PER_MIN", "2")
    c = create_app().test_client()
    payload = {"weights": DEFAULT_WEIGHTS, "scenario_id": "GFC_2008"}
    codes = [c.post("/api/portfolio/stress-test", json=payload).status_code for _ in range(4)]
    assert codes[:2] == [200, 200] and 429 in codes          # open, then limiter fires
