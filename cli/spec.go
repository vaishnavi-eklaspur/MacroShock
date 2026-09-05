package main

import (
	"bytes"
	"fmt"
	"os"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"
)

// Spec mirrors backend/workflow/spec.py.
//
// The validation is duplicated on purpose: the CLI rejects a malformed specification locally,
// before spending a network round-trip or a worker slot on it. The server re-validates anyway —
// a client is never a trust boundary — but a scientist iterating on a spec gets an instant,
// precise error instead of a queued job that fails minutes later.
type Spec struct {
	Version  string         `yaml:"version"`
	Metadata map[string]any `yaml:"metadata"`
	Inputs   Inputs         `yaml:"inputs"`
	Workflow Workflow       `yaml:"workflow"`
	Outputs  Outputs        `yaml:"outputs"`
}

type Inputs struct {
	Data       Data               `yaml:"data"`
	Portfolio  map[string]float64 `yaml:"portfolio"`
	Parameters map[string]any     `yaml:"parameters"`
}

type Data struct {
	Source        string `yaml:"source"`
	AssetReturns  string `yaml:"asset_returns"`
	FactorReturns string `yaml:"factor_returns"`
	Start         string `yaml:"start"`
}

type Step struct {
	Name string         `yaml:"name"`
	Run  string         `yaml:"run"`
	With map[string]any `yaml:"with"`
}

type Workflow struct {
	Type  string `yaml:"type"`
	Steps []Step `yaml:"steps"`
}

type Outputs struct {
	Directory string   `yaml:"directory"`
	Files     []string `yaml:"files"`
}

// validSteps are the analysis steps the engine can run; kept in sync with StepName in spec.py.
var validSteps = map[string]bool{
	"meta":               true,
	"exposures":          true,
	"risk-contribution":  true,
	"factor-regression":  true,
	"stress-test":        true,
	"custom-stress-test": true,
	"active-risk":        true,
	"reverse-stress":     true,
	"backtest":           true,
}

func validStepNames() []string {
	names := make([]string, 0, len(validSteps))
	for name := range validSteps {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// LoadSpec reads and parses a specification, returning the parsed form and the original bytes.
// The raw document is preserved so submission forwards exactly what the author wrote rather than
// a re-serialised approximation of it.
func LoadSpec(path string) (*Spec, []byte, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, nil, fmt.Errorf("reading %s: %w", path, err)
	}
	var spec Spec
	dec := yaml.NewDecoder(bytes.NewReader(raw))
	dec.KnownFields(true) // a typo must fail, not be silently ignored
	if err := dec.Decode(&spec); err != nil {
		return nil, nil, fmt.Errorf("parsing %s: %w", path, err)
	}
	return &spec, raw, nil
}

// Validate reports every problem at once, so one run fixes the whole file.
func (s *Spec) Validate() error {
	var problems []string
	add := func(format string, args ...any) {
		problems = append(problems, fmt.Sprintf(format, args...))
	}

	if len(s.Inputs.Portfolio) == 0 {
		add("inputs.portfolio must contain at least one holding")
	}
	total := 0.0
	for ticker, weight := range s.Inputs.Portfolio {
		if weight < 0 {
			add("inputs.portfolio[%q] must be non-negative (got %g)", ticker, weight)
		}
		total += weight
	}
	if len(s.Inputs.Portfolio) > 0 && total <= 0 {
		add("inputs.portfolio weights must sum to a positive value")
	}

	if s.Inputs.Data.Source == "csv" && s.Inputs.Data.AssetReturns == "" {
		add("inputs.data.asset_returns is required when inputs.data.source is \"csv\"")
	}
	switch s.Inputs.Data.Source {
	case "", "csv", "synthetic", "yahoo":
	default:
		add("inputs.data.source %q is not one of csv, synthetic, yahoo", s.Inputs.Data.Source)
	}

	if s.Workflow.Type != "" && s.Workflow.Type != "serial" {
		add("workflow.type %q is not supported (want \"serial\")", s.Workflow.Type)
	}
	if len(s.Workflow.Steps) == 0 {
		add("workflow.steps must contain at least one step")
	}

	seen := make(map[string]bool, len(s.Workflow.Steps))
	for i, step := range s.Workflow.Steps {
		if step.Name == "" {
			add("workflow.steps[%d].name is required", i)
		}
		if seen[step.Name] {
			add("duplicate step name %q", step.Name)
		}
		seen[step.Name] = true

		if !validSteps[step.Run] {
			add("step %q: unknown run %q (valid: %s)",
				step.Name, step.Run, strings.Join(validStepNames(), ", "))
			continue
		}
		// Required per-step parameters, resolvable from the step or the global block.
		if step.Run == "stress-test" && !s.hasParam(step, "scenario_id") {
			add("step %q: run \"stress-test\" requires parameter \"scenario_id\"", step.Name)
		}
		if step.Run == "custom-stress-test" && !s.hasParam(step, "shocks") {
			add("step %q: run \"custom-stress-test\" requires parameter \"shocks\"", step.Name)
		}
	}

	if len(problems) == 0 {
		return nil
	}
	sort.Strings(problems)
	return fmt.Errorf("%d problem(s) found:\n  - %s", len(problems), strings.Join(problems, "\n  - "))
}

// hasParam reports whether a parameter is supplied on the step or in the global parameters.
func (s *Spec) hasParam(step Step, key string) bool {
	if _, ok := step.With[key]; ok {
		return true
	}
	_, ok := s.Inputs.Parameters[key]
	return ok
}
