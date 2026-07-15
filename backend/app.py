"""MacroShock Flask API.

Separates business logic (analytics engine) from presentation (Streamlit). Requests are
validated with pydantic; expensive endpoints are Redis-cached with a model-versioned key.

Endpoints
---------
GET  /health
GET  /api/meta                           model version, shrinkage, regime stats, factors
GET  /api/assets
GET  /api/scenarios
POST /api/portfolio/load                 validate a portfolio definition
POST /api/portfolio/risk-contribution    calm vs. crisis-regime MCTR decomposition
POST /api/portfolio/factor-regression    OLS factor betas with t-stats and R^2
POST /api/portfolio/stress-test          drawdown + attribution + tail VaR + rebalance + commentary
POST /api/portfolio/reverse-stress-test  constrained most-plausible shock + top-k narratives
POST /api/portfolio/rebalance            mitigation trade only
GET  /api/backtest                       model-predicted vs realized crisis returns
"""
from __future__ import annotations

import logging
import time

from flask import Flask, jsonify, request
from pydantic import ValidationError

from analytics import factors as factors_mod
from analytics import rebalance as rebalance_mod
from analytics.engine import MacroShockEngine, _rebalance_dict
from cache import Cache
from schemas import RebalanceRequest, ReverseRequest, StressRequest, WeightsRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("macroshock.api")


def create_app() -> Flask:
    app = Flask(__name__)
    engine = MacroShockEngine()
    cache = Cache()

    def check_tickers(weights: dict[str, float]) -> None:
        unknown = set(weights) - set(engine.tickers)
        if unknown:
            raise ValueError(f"Unknown ticker(s) {sorted(unknown)}. Valid: {engine.tickers}")

    @app.errorhandler(ValidationError)
    def _validation(exc: ValidationError):
        first = exc.errors()[0]
        return jsonify({"error": first.get("msg", "Invalid request."), "details": exc.errors()}), 400

    @app.errorhandler(ValueError)
    def _bad_request(exc: ValueError):
        return jsonify({"error": str(exc)}), 400

    @app.errorhandler(KeyError)
    def _not_found(exc: KeyError):
        return jsonify({"error": str(exc).strip('"')}), 404

    # ---------------------------------------------------------------- meta / reference
    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "cache_enabled": cache.enabled,
                        "model_version": engine.model_version, "assets": engine.tickers})

    @app.get("/api/meta")
    def meta():
        return jsonify(engine.meta())

    @app.get("/api/assets")
    def assets():
        return jsonify({"assets": engine.asset_reference()})

    @app.get("/api/scenarios")
    def scenarios():
        return jsonify({"scenarios": engine.list_scenarios()})

    @app.get("/api/backtest")
    def backtest():
        result, hit = cache.get_or_compute("backtest", {"v": engine.model_version},
                                           engine.backtest)
        result["cache_hit"] = hit
        return jsonify(result)

    # ---------------------------------------------------------------- portfolio
    @app.post("/api/portfolio/load")
    def load():
        req = WeightsRequest(**(request.get_json(force=True) or {}))
        check_tickers(req.weights)
        total = sum(req.weights.values())
        return jsonify({"weights": {t: w / total for t, w in req.weights.items()},
                        "was_normalized": abs(total - 1.0) > 1e-9,
                        "message": "Portfolio validated."})

    @app.post("/api/portfolio/risk-contribution")
    def risk_contribution():
        req = WeightsRequest(**(request.get_json(force=True) or {}))
        check_tickers(req.weights)
        result, hit = cache.get_or_compute("risk", {"weights": req.weights},
                                           lambda: engine.risk_report(req.weights))
        result["cache_hit"] = hit
        return jsonify(result)

    @app.post("/api/portfolio/factor-regression")
    def factor_regression():
        req = WeightsRequest(**(request.get_json(force=True) or {}))
        check_tickers(req.weights)
        result, hit = cache.get_or_compute("regression", {"weights": req.weights},
                                           lambda: engine.factor_regression(req.weights))
        result["cache_hit"] = hit
        return jsonify(result)

    @app.post("/api/portfolio/stress-test")
    def stress_test():
        req = StressRequest(**(request.get_json(force=True) or {}))
        check_tickers(req.weights)
        if req.scenario_id not in engine.scenarios:
            raise KeyError(f"Unknown scenario_id '{req.scenario_id}'")
        started = time.perf_counter()
        result, hit = cache.get_or_compute(
            "stress",
            {"weights": req.weights, "scenario_id": req.scenario_id, "confidence": req.confidence},
            lambda: engine.stress_test(req.weights, req.scenario_id, req.confidence),
        )
        result["cache_hit"] = hit
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return jsonify(result)

    @app.post("/api/portfolio/reverse-stress-test")
    def reverse_stress_test():
        req = ReverseRequest(**(request.get_json(force=True) or {}))
        check_tickers(req.weights)
        result, hit = cache.get_or_compute(
            "reverse", {"weights": req.weights, "target_loss": req.target_loss},
            lambda: engine.reverse_stress(req.weights, req.target_loss),
        )
        result["cache_hit"] = hit
        return jsonify(result)

    @app.post("/api/portfolio/rebalance")
    def rebalance_only():
        req = RebalanceRequest(**(request.get_json(force=True) or {}))
        check_tickers(req.weights)
        if req.scenario_id not in engine.scenarios:
            raise KeyError(f"Unknown scenario_id '{req.scenario_id}'")
        w = engine.weight_vector(req.weights)
        shocks = engine.scenarios[req.scenario_id]["shocks"]
        asset_scn = factors_mod.scenario_asset_returns(engine.assets, shocks)
        rec = rebalance_mod.recommend_rebalance(w, engine.tickers, asset_scn, engine.stressed_cov)
        return jsonify(_rebalance_dict(rec))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
