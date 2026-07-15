"""Pydantic request schemas.

Decouples the public API contract from internal data structures and gives clear,
structured validation errors. Ticker validity is checked in the app layer (it depends on
the loaded universe); here we enforce structure, numeric sanity and bounds.
"""
from __future__ import annotations

import math

from pydantic import BaseModel, Field, field_validator


class WeightsRequest(BaseModel):
    weights: dict[str, float] = Field(..., description="Mapping {ticker: weight}; normalized server-side.")

    @field_validator("weights")
    @classmethod
    def _validate_weights(cls, v: dict[str, float]) -> dict[str, float]:
        if not v:
            raise ValueError("'weights' must be a non-empty object of {ticker: weight}.")
        for ticker, w in v.items():
            if not isinstance(w, (int, float)) or not math.isfinite(w):
                raise ValueError(f"Weight for '{ticker}' must be a finite number.")
            if w < 0:
                raise ValueError("Long-only portfolio: weights must be non-negative.")
        if sum(v.values()) <= 0:
            raise ValueError("Weights must sum to a positive value.")
        return v


class StressRequest(WeightsRequest):
    scenario_id: str = Field(..., min_length=1)
    confidence: float = Field(0.95, gt=0.5, lt=1.0)


class ReverseRequest(WeightsRequest):
    target_loss: float = Field(0.20, gt=0.0, lt=1.0)


class RebalanceRequest(WeightsRequest):
    scenario_id: str = Field(..., min_length=1)


class CustomStressRequest(WeightsRequest):
    """A user-defined stress scenario: an arbitrary factor-shock vector."""
    shocks: dict[str, float] = Field(..., description="Mapping {factor_name: shock} in native units.")
    name: str = Field("Custom scenario", max_length=120)
    confidence: float = Field(0.95, gt=0.5, lt=1.0)

    @field_validator("shocks")
    @classmethod
    def _finite_shocks(cls, v: dict[str, float]) -> dict[str, float]:
        if not v:
            raise ValueError("'shocks' must be a non-empty object of {factor: shock}.")
        for factor, s in v.items():
            if not isinstance(s, (int, float)) or not math.isfinite(s):
                raise ValueError(f"Shock for '{factor}' must be a finite number.")
        return v
