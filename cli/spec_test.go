package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const validSpec = `
version: "1.0"
metadata:
  name: test
inputs:
  data:
    source: synthetic
  portfolio:
    SPY: 0.6
    IEF: 0.4
  parameters:
    confidence: 0.95
workflow:
  type: serial
  steps:
    - name: risk
      run: risk-contribution
    - name: gfc
      run: stress-test
      with:
        scenario_id: GFC_2008
outputs:
  directory: results
`

func writeSpec(t *testing.T, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "spec.yaml")
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatalf("writing spec: %v", err)
	}
	return path
}

func mustLoad(t *testing.T, content string) *Spec {
	t.Helper()
	spec, raw, err := LoadSpec(writeSpec(t, content))
	if err != nil {
		t.Fatalf("LoadSpec: %v", err)
	}
	if len(raw) == 0 {
		t.Fatal("expected the raw document to be preserved for submission")
	}
	return spec
}

func TestValidSpecPasses(t *testing.T) {
	spec := mustLoad(t, validSpec)
	if err := spec.Validate(); err != nil {
		t.Fatalf("expected valid spec, got: %v", err)
	}
	if len(spec.Workflow.Steps) != 2 {
		t.Fatalf("expected 2 steps, got %d", len(spec.Workflow.Steps))
	}
	if spec.Workflow.Steps[1].With["scenario_id"] != "GFC_2008" {
		t.Fatalf("step `with` block not parsed: %#v", spec.Workflow.Steps[1].With)
	}
}

func TestUnknownFieldIsRejected(t *testing.T) {
	// KnownFields(true): a typo must fail rather than be silently dropped.
	bad := strings.Replace(validSpec, "  portfolio:", "  portfoliooo:", 1)
	if _, _, err := LoadSpec(writeSpec(t, bad)); err == nil {
		t.Fatal("expected a parse error for an unknown field")
	}
}

func TestUnknownStepIsRejected(t *testing.T) {
	spec := mustLoad(t, strings.Replace(validSpec, "run: risk-contribution", "run: not-a-step", 1))
	err := spec.Validate()
	if err == nil || !strings.Contains(err.Error(), "unknown run") {
		t.Fatalf("expected an unknown-step error, got: %v", err)
	}
}

func TestNegativeWeightIsRejected(t *testing.T) {
	spec := mustLoad(t, strings.Replace(validSpec, "SPY: 0.6", "SPY: -0.6", 1))
	err := spec.Validate()
	if err == nil || !strings.Contains(err.Error(), "non-negative") {
		t.Fatalf("expected a non-negative weight error, got: %v", err)
	}
}

func TestDuplicateStepNamesAreRejected(t *testing.T) {
	spec := mustLoad(t, strings.Replace(validSpec, "name: gfc", "name: risk", 1))
	err := spec.Validate()
	if err == nil || !strings.Contains(err.Error(), "duplicate step name") {
		t.Fatalf("expected a duplicate-name error, got: %v", err)
	}
}

func TestStressTestRequiresScenarioID(t *testing.T) {
	bad := strings.Replace(validSpec, "      with:\n        scenario_id: GFC_2008\n", "", 1)
	spec := mustLoad(t, bad)
	err := spec.Validate()
	if err == nil || !strings.Contains(err.Error(), "scenario_id") {
		t.Fatalf("expected a missing-scenario_id error, got: %v", err)
	}
}

func TestGlobalParameterSatisfiesAStepRequirement(t *testing.T) {
	// scenario_id supplied globally rather than per step is legitimate.
	s := strings.Replace(validSpec, "      with:\n        scenario_id: GFC_2008\n", "", 1)
	s = strings.Replace(s, "    confidence: 0.95", "    confidence: 0.95\n    scenario_id: GFC_2008", 1)
	if err := mustLoad(t, s).Validate(); err != nil {
		t.Fatalf("expected a globally-supplied parameter to satisfy the step: %v", err)
	}
}

func TestCSVSourceRequiresAssetReturns(t *testing.T) {
	spec := mustLoad(t, strings.Replace(validSpec, "source: synthetic", "source: csv", 1))
	err := spec.Validate()
	if err == nil || !strings.Contains(err.Error(), "asset_returns") {
		t.Fatalf("expected an asset_returns requirement, got: %v", err)
	}
}

func TestAllProblemsAreReportedTogether(t *testing.T) {
	s := strings.Replace(validSpec, "SPY: 0.6", "SPY: -0.6", 1)
	s = strings.Replace(s, "run: risk-contribution", "run: nope", 1)
	err := mustLoad(t, s).Validate()
	if err == nil {
		t.Fatal("expected errors")
	}
	// One run should surface every problem, not just the first.
	if !strings.Contains(err.Error(), "non-negative") || !strings.Contains(err.Error(), "unknown run") {
		t.Fatalf("expected both problems reported, got: %v", err)
	}
}
