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
POST /api/portfolio/custom-stress-test   same, against a user-defined factor-shock vector
POST /api/portfolio/active-risk          benchmark-relative: tracking error, active risk, tilts
POST /api/portfolio/reverse-stress-test  constrained most-plausible shock + top-k narratives
POST /api/portfolio/rebalance            mitigation trade only
GET  /api/backtest                       model-predicted vs realized crisis returns
GET  /api/portfolios                     list server-saved portfolios
POST /api/portfolios                     save/upsert a named portfolio
DELETE /api/portfolios/<name>            delete a saved portfolio

Auth: set MACROSHOCK_API_KEY to require an X-API-Key header on POST/DELETE (unset = open,
for local demos). A lightweight in-process rate limiter caps POST/DELETE per IP per minute.
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict

from flask import Flask, g, jsonify, request
from flask_cors import CORS
from pydantic import ValidationError

from data import database

from analytics import factors as factors_mod
from analytics import rebalance as rebalance_mod
from analytics.engine import MacroShockEngine, _optimized_rebalance_dict
from cache import Cache
from schemas import (
    ActiveRiskRequest,
    CustomStressRequest,
    RebalanceRequest,
    ReverseRequest,
    StressRequest,
    WeightsRequest,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("macroshock.api")


def create_app() -> Flask:
    app = Flask(__name__)
    # CORS so a browser-hosted client (the React app on another origin) can call the API.
    # Restrict to CORS_ORIGINS (comma-separated) in prod; '*' is fine for a read API with no
    # cookies (writes are guarded by the API key, not the browser origin).
    CORS(app, resources={r"/api/*": {"origins": os.getenv("CORS_ORIGINS", "*").split(",")},
                         r"/health": {"origins": "*"}})
    engine = MacroShockEngine()
    cache = Cache()

    api_key = os.getenv("MACROSHOCK_API_KEY")            # unset => open (local demo)
    rate_per_min = int(os.getenv("MACROSHOCK_RATE_PER_MIN", "120"))
    hits: dict[str, list[float]] = defaultdict(list)
    metrics: dict[str, int] = defaultdict(int)           # {(path,status): count}

    @app.before_request
    def _guard():
        g.t0 = time.perf_counter()
        # Optional API-key auth on mutating/compute endpoints; GET/health stay open.
        if api_key and request.method in ("POST", "DELETE"):
            if request.headers.get("X-API-Key") != api_key:
                return jsonify({"error": "Unauthorized: missing or invalid X-API-Key."}), 401
        if request.method in ("POST", "DELETE"):
            ip = request.remote_addr or "?"
            allowed = cache.rate_hit(ip, rate_per_min)   # Redis-backed, shared across workers
            if allowed is None:                          # Redis down: in-process fallback
                now = time.time()
                recent = hits[ip] = [t for t in hits[ip] if now - t < 60]
                allowed = len(recent) < rate_per_min
                if allowed:
                    recent.append(now)
            if not allowed:
                return jsonify({"error": "Rate limit exceeded; slow down."}), 429

    @app.after_request
    def _observe(resp):
        path = (request.url_rule.rule if request.url_rule else request.path)
        metrics[f'{path}|{resp.status_code}'] += 1
        dt_ms = (time.perf_counter() - getattr(g, "t0", time.perf_counter())) * 1000
        logger.info('method=%s path=%s status=%s latency_ms=%.1f',
                    request.method, path, resp.status_code, dt_ms)
        return resp

    @app.get("/metrics")
    def prometheus_metrics():
        lines = ["# HELP macroshock_requests_total Total HTTP requests by route and status.",
                 "# TYPE macroshock_requests_total counter"]
        for k, v in metrics.items():
            path, status = k.rsplit("|", 1)
            lines.append(f'macroshock_requests_total{{path="{path}",status="{status}"}} {v}')
        return "\n".join(lines) + "\n", 200, {"Content-Type": "text/plain; version=0.0.4"}

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

    @app.get("/")
    def index():
        # Friendly API index so hitting the base URL in a browser isn't a bare 404.
        return jsonify({
            "service": "MacroShock API",
            "model_version": engine.model_version,
            "docs": "docs/METHODOLOGY.md, docs/DESIGN_AND_MATH.md",
            "dashboards": {"streamlit": "http://localhost:8501", "react": "http://localhost:5173"},
            "endpoints": {
                "GET": ["/health", "/metrics", "/api/meta", "/api/assets", "/api/scenarios",
                        "/api/benchmarks", "/api/exposures", "/api/backtest", "/api/portfolios"],
                "POST": ["/api/portfolio/load", "/api/portfolio/stress-test",
                         "/api/portfolio/custom-stress-test", "/api/portfolio/active-risk",
                         "/api/portfolio/reverse-stress-test", "/api/portfolio/rebalance",
                         "/api/portfolio/risk-contribution", "/api/portfolio/factor-regression"],
            },
        })

    # ---------------------------------------------------------------- meta / reference
    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "cache_enabled": cache.enabled,
                        "model_version": engine.model_version, "assets": engine.tickers,
                        "data_source": engine.dataset_meta.get("source", "unknown")})

    @app.get("/api/meta")
    def meta():
        return jsonify(engine.meta())

    @app.get("/api/assets")
    def assets():
        return jsonify({"assets": engine.asset_reference()})

    @app.get("/api/scenarios")
    def scenarios():
        return jsonify({"scenarios": engine.list_scenarios()})

    @app.get("/api/exposures")
    def exposures():
        return jsonify(engine.exposure_report())

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

    @app.get("/api/benchmarks")
    def benchmarks():
        return jsonify({"benchmarks": engine.benchmarks()})

    @app.post("/api/portfolio/active-risk")
    def active_risk():
        req = ActiveRiskRequest(**(request.get_json(force=True) or {}))
        check_tickers(req.weights)
        if req.benchmark_weights:
            check_tickers(req.benchmark_weights)
            bench = req.benchmark_weights
        else:
            bench = req.benchmark_id or "US 60/40"
        result, hit = cache.get_or_compute(
            "active", {"weights": req.weights, "bench": bench},
            lambda: engine.active_risk(req.weights, bench))
        result["cache_hit"] = hit
        return jsonify(result)

    @app.post("/api/portfolio/custom-stress-test")
    def custom_stress_test():
        req = CustomStressRequest(**(request.get_json(force=True) or {}))
        check_tickers(req.weights)
        unknown = set(req.shocks) - set(engine.factor_names)
        if unknown:
            raise ValueError(f"Unknown factor(s) {sorted(unknown)}. Valid: {engine.factor_names}")
        result, hit = cache.get_or_compute(
            "custom",
            {"weights": req.weights, "shocks": req.shocks, "confidence": req.confidence},
            lambda: engine.custom_stress_test(req.weights, req.shocks, req.name, req.confidence),
        )
        result["cache_hit"] = hit
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
        rec = rebalance_mod.optimize_rebalance(w, engine.tickers, asset_scn, engine.stressed_cov)
        return jsonify(_optimized_rebalance_dict(rec))

    # ---------------------------------------------------------------- saved portfolios
    @app.get("/api/portfolios")
    def list_portfolios():
        return jsonify({"portfolios": database.list_portfolios(engine.db_path)})

    @app.post("/api/portfolios")
    def save_portfolio():
        body = request.get_json(force=True) or {}
        req = WeightsRequest(weights=body.get("weights", {}))
        check_tickers(req.weights)
        name = str(body.get("name", "")).strip()
        if not name:
            raise ValueError("A non-empty 'name' is required.")
        database.save_portfolio(name, req.weights, engine.db_path)
        return jsonify({"saved": name}), 201

    @app.delete("/api/portfolios/<name>")
    def delete_portfolio(name: str):
        if not database.delete_portfolio(name, engine.db_path):
            raise KeyError(f"No saved portfolio named '{name}'")
        return jsonify({"deleted": name})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
