"""MacroShock Flask API.

Separates business logic (analytics engine) from presentation (Streamlit). Endpoints return
structured JSON with clear validation errors. Expensive endpoints are Redis-cached.

Endpoints
---------
GET  /health
GET  /api/assets
GET  /api/scenarios
POST /api/portfolio/load                 validate a portfolio definition
POST /api/portfolio/risk-contribution    MCTR / CCTR / PCTR decomposition
POST /api/portfolio/factor-regression    OLS factor betas
POST /api/portfolio/stress-test          scenario drawdown + attribution + rebalance + commentary
POST /api/portfolio/reverse-stress-test  most-plausible shock for a target loss
POST /api/portfolio/rebalance            mitigation trade only
"""
from __future__ import annotations

import logging
import time

from flask import Flask, jsonify, request

from analytics.engine import MacroShockEngine
from analytics import rebalance as rebalance_mod
from analytics import factors as factors_mod
from cache import Cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("macroshock.api")


def create_app() -> Flask:
    app = Flask(__name__)
    engine = MacroShockEngine()
    cache = Cache()

    # ---------------------------------------------------------------- validation
    def parse_weights(body: dict) -> dict[str, float]:
        weights = body.get("weights")
        if not isinstance(weights, dict) or not weights:
            raise ValueError("'weights' must be a non-empty object of {ticker: weight}.")
        valid = set(engine.tickers)
        cleaned: dict[str, float] = {}
        for ticker, w in weights.items():
            if ticker not in valid:
                raise ValueError(f"Unknown ticker '{ticker}'. Valid: {sorted(valid)}")
            try:
                cleaned[ticker] = float(w)
            except (TypeError, ValueError):
                raise ValueError(f"Weight for '{ticker}' must be numeric.")
        if any(v < 0 for v in cleaned.values()):
            raise ValueError("Long-only portfolio: weights must be non-negative.")
        if sum(cleaned.values()) <= 0:
            raise ValueError("Weights must sum to a positive value.")
        return cleaned

    def confidence(body: dict) -> float:
        alpha = float(body.get("confidence", 0.95))
        if not 0.5 < alpha < 1.0:
            raise ValueError("'confidence' must be in (0.5, 1.0), e.g. 0.95.")
        return alpha

    @app.errorhandler(ValueError)
    def _bad_request(exc: ValueError):
        return jsonify({"error": str(exc)}), 400

    @app.errorhandler(KeyError)
    def _not_found(exc: KeyError):
        return jsonify({"error": str(exc).strip('"')}), 404

    # ---------------------------------------------------------------- routes
    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "cache_enabled": cache.enabled,
                        "assets": engine.tickers})

    @app.get("/api/assets")
    def assets():
        return jsonify({"assets": engine.asset_reference()})

    @app.get("/api/scenarios")
    def scenarios():
        return jsonify({"scenarios": engine.list_scenarios()})

    @app.post("/api/portfolio/load")
    def load():
        body = request.get_json(force=True) or {}
        weights = parse_weights(body)
        total = sum(weights.values())
        normalized = {t: w / total for t, w in weights.items()}
        return jsonify({"weights": normalized, "normalized": abs(total - 1.0) > 1e-9,
                        "message": "Portfolio validated."})

    @app.post("/api/portfolio/risk-contribution")
    def risk_contribution():
        body = request.get_json(force=True) or {}
        weights = parse_weights(body)
        result, hit = cache.get_or_compute(
            "risk", {"weights": weights}, lambda: engine.risk_report(weights))
        result["cache_hit"] = hit
        return jsonify(result)

    @app.post("/api/portfolio/factor-regression")
    def factor_regression():
        body = request.get_json(force=True) or {}
        weights = parse_weights(body)
        result, hit = cache.get_or_compute(
            "regression", {"weights": weights}, lambda: engine.factor_regression(weights))
        result["cache_hit"] = hit
        return jsonify(result)

    @app.post("/api/portfolio/stress-test")
    def stress_test():
        body = request.get_json(force=True) or {}
        weights = parse_weights(body)
        alpha = confidence(body)
        scenario_id = body.get("scenario_id")
        if not scenario_id:
            raise ValueError("'scenario_id' is required.")

        started = time.perf_counter()
        result, hit = cache.get_or_compute(
            "stress",
            {"weights": weights, "scenario_id": scenario_id, "confidence": alpha},
            lambda: engine.stress_test(weights, scenario_id, alpha),
        )
        result["cache_hit"] = hit
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return jsonify(result)

    @app.post("/api/portfolio/reverse-stress-test")
    def reverse_stress_test():
        body = request.get_json(force=True) or {}
        weights = parse_weights(body)
        target_loss = float(body.get("target_loss", 0.20))
        if not 0.0 < target_loss < 1.0:
            raise ValueError("'target_loss' must be in (0, 1), e.g. 0.20 for 20%.")
        result, hit = cache.get_or_compute(
            "reverse",
            {"weights": weights, "target_loss": target_loss},
            lambda: engine.reverse_stress(weights, target_loss),
        )
        result["cache_hit"] = hit
        return jsonify(result)

    @app.post("/api/portfolio/rebalance")
    def rebalance_only():
        body = request.get_json(force=True) or {}
        weights = parse_weights(body)
        scenario_id = body.get("scenario_id")
        if not scenario_id or scenario_id not in engine.scenarios:
            raise ValueError("'scenario_id' is required and must be valid.")
        w = engine._weight_vector(weights)  # noqa: SLF001 - internal helper reuse
        shocks = engine.scenarios[scenario_id]["shocks"]
        asset_scn = factors_mod.scenario_asset_returns(engine.assets, shocks)
        rec = rebalance_mod.recommend_rebalance(w, engine.tickers, asset_scn, engine.cov)
        return jsonify(rec.__dict__)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
