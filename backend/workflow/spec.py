"""Schema and loader for a `macroshock.yaml` workflow specification.

Validation is strict and happens before any computation: an invalid spec fails loudly with a
precise message rather than half-running a pipeline. Unknown fields are rejected, so a typo in a
step name can never be silently ignored — the whole point of a declarative spec is that what you
wrote is what runs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Analysis steps a workflow may request; the runner maps each to an engine call.
StepName = Literal[
    "meta",
    "exposures",
    "risk-contribution",
    "factor-regression",
    "stress-test",
    "custom-stress-test",
    "active-risk",
    "reverse-stress",
    "backtest",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataSpec(_Strict):
    """Where the return history comes from. 'csv' pins the analysis to a committed snapshot."""

    source: Literal["csv", "synthetic", "yahoo"] = "csv"
    asset_returns: str | None = None
    factor_returns: str | None = None
    start: str | None = None

    @field_validator("asset_returns")
    @classmethod
    def _csv_needs_a_file(cls, v, info):
        if info.data.get("source") == "csv" and not v:
            raise ValueError("inputs.data.asset_returns is required when source is 'csv'.")
        return v


class InputsSpec(_Strict):
    data: DataSpec = Field(default_factory=DataSpec)
    portfolio: dict[str, float]
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("portfolio")
    @classmethod
    def _non_empty_non_negative(cls, v: dict[str, float]) -> dict[str, float]:
        if not v:
            raise ValueError("inputs.portfolio must map at least one ticker to a weight.")
        for ticker, w in v.items():
            if not isinstance(w, (int, float)) or w < 0:
                raise ValueError(f"inputs.portfolio['{ticker}'] must be a non-negative number.")
        if sum(v.values()) <= 0:
            raise ValueError("inputs.portfolio weights must sum to a positive value.")
        return v


class StepSpec(_Strict):
    # `with` is a Python keyword, so it is accepted under an alias.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(..., min_length=1)
    run: StepName
    with_: dict[str, Any] = Field(default_factory=dict, alias="with")


class WorkflowSpec(_Strict):
    type: Literal["serial"] = "serial"
    steps: list[StepSpec]

    @field_validator("steps")
    @classmethod
    def _unique_non_empty(cls, v: list[StepSpec]) -> list[StepSpec]:
        if not v:
            raise ValueError("workflow.steps must contain at least one step.")
        names = [s.name for s in v]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"workflow step names must be unique; duplicated: {dupes}")
        return v


class OutputsSpec(_Strict):
    directory: str = "results"
    files: list[str] = Field(default_factory=list)


class MacroShockSpec(_Strict):
    version: str = "1.0"
    metadata: dict[str, Any] = Field(default_factory=dict)
    inputs: InputsSpec
    workflow: WorkflowSpec
    outputs: OutputsSpec = Field(default_factory=OutputsSpec)


def load_spec(path: str | Path) -> MacroShockSpec:
    """Parse and validate a workflow spec, raising ValueError with a precise message if invalid.

    Relative data paths resolve against the spec file's own directory (the docker-compose
    convention), so a spec is portable: it runs the same from the repo root, from `backend/`,
    or from inside the container.
    """
    spec_path = Path(path)
    raw = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level.")
    spec = MacroShockSpec(**raw)

    base = spec_path.resolve().parent
    for field in ("asset_returns", "factor_returns"):
        value = getattr(spec.inputs.data, field)
        if value and not Path(value).is_absolute() and not Path(value).exists():
            candidate = base / value
            if candidate.exists():
                setattr(spec.inputs.data, field, str(candidate))
    return spec
