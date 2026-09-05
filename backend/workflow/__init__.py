"""Declarative workflow engine.

Runs a MacroShock analysis from a YAML specification instead of ad-hoc API calls, so an analysis
becomes a versionable artifact: the same spec against the same pinned data yields the same
results. The shape deliberately mirrors REANA's model (inputs / workflow steps / outputs) so a
spec can be executed locally, inside the container image, or as a REANA serial workflow without
changing anything.
"""
from .runner import run_workflow
from .spec import MacroShockSpec, load_spec

__all__ = ["MacroShockSpec", "load_spec", "run_workflow"]
