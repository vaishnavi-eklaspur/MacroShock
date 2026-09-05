// Command macroshock-cli validates and submits declarative MacroShock analyses.
//
//	macroshock-cli validate macroshock.yaml
//	macroshock-cli submit   macroshock.yaml --wait
//	macroshock-cli status   <job-id>
//
// It is a thin, fast front end to the Python compute service: it parses and validates the
// specification locally (so authoring errors surface instantly), then forwards the original
// document to the API, which re-validates and queues it for a worker.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"
)

const defaultAPI = "http://localhost:5000"

func usage() {
	fmt.Fprint(os.Stderr, `macroshock-cli - run declarative MacroShock analyses

Usage:
  macroshock-cli validate <spec.yaml>
  macroshock-cli submit   <spec.yaml> [--api URL] [--api-key KEY] [--wait] [--timeout 10m]
  macroshock-cli status   <job-id>    [--api URL] [--api-key KEY]

Environment:
  MACROSHOCK_API       default API base URL (default `+defaultAPI+`)
  MACROSHOCK_API_KEY   API key sent as X-API-Key
`)
}

func apiDefault() string {
	if v := os.Getenv("MACROSHOCK_API"); v != "" {
		return v
	}
	return defaultAPI
}

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}

	switch os.Args[1] {
	case "validate":
		os.Exit(cmdValidate(os.Args[2:]))
	case "submit":
		os.Exit(cmdSubmit(os.Args[2:]))
	case "status":
		os.Exit(cmdStatus(os.Args[2:]))
	case "-h", "--help", "help":
		usage()
		os.Exit(0)
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n\n", os.Args[1])
		usage()
		os.Exit(2)
	}
}

func cmdValidate(args []string) int {
	fs := flag.NewFlagSet("validate", flag.ExitOnError)
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if fs.NArg() != 1 {
		fmt.Fprintln(os.Stderr, "usage: macroshock-cli validate <spec.yaml>")
		return 2
	}

	spec, _, err := LoadSpec(fs.Arg(0))
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		return 2
	}
	if err := spec.Validate(); err != nil {
		fmt.Fprintf(os.Stderr, "%s is invalid: %v\n", fs.Arg(0), err)
		return 1
	}
	fmt.Printf("%s: valid (%d step(s), %d holding(s))\n",
		fs.Arg(0), len(spec.Workflow.Steps), len(spec.Inputs.Portfolio))
	return 0
}

func cmdSubmit(args []string) int {
	fs := flag.NewFlagSet("submit", flag.ExitOnError)
	api := fs.String("api", apiDefault(), "API base URL")
	key := fs.String("api-key", os.Getenv("MACROSHOCK_API_KEY"), "API key (X-API-Key)")
	wait := fs.Bool("wait", false, "poll until the job reaches a terminal state")
	timeout := fs.Duration("timeout", 10*time.Minute, "how long to wait with --wait")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if fs.NArg() != 1 {
		fmt.Fprintln(os.Stderr, "usage: macroshock-cli submit <spec.yaml> [flags]")
		return 2
	}

	spec, raw, err := LoadSpec(fs.Arg(0))
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		return 2
	}
	// Fail locally before consuming a worker slot.
	if err := spec.Validate(); err != nil {
		fmt.Fprintf(os.Stderr, "%s is invalid: %v\n", fs.Arg(0), err)
		return 1
	}

	client := NewClient(*api, *key)
	job, err := client.Submit(raw)
	if err != nil {
		fmt.Fprintf(os.Stderr, "submit failed: %v\n", err)
		return 1
	}
	fmt.Printf("submitted %s (status %s, mode %s)\n", job.JobID, job.Status, job.Mode)

	if !*wait {
		return 0
	}
	final, err := client.Wait(job.JobID, 2*time.Second, *timeout)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		return 1
	}
	return report(final)
}

func cmdStatus(args []string) int {
	fs := flag.NewFlagSet("status", flag.ExitOnError)
	api := fs.String("api", apiDefault(), "API base URL")
	key := fs.String("api-key", os.Getenv("MACROSHOCK_API_KEY"), "API key (X-API-Key)")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if fs.NArg() != 1 {
		fmt.Fprintln(os.Stderr, "usage: macroshock-cli status <job-id> [flags]")
		return 2
	}

	job, err := NewClient(*api, *key).Status(fs.Arg(0))
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		return 1
	}
	return report(job)
}

// report prints a terminal job record and maps failure to a non-zero exit code, so the CLI
// composes properly in a shell pipeline or a CI step.
func report(job *Job) int {
	if job.Status == "FAILURE" {
		fmt.Fprintf(os.Stderr, "job %s failed: %s\n", job.JobID, job.Error)
		return 1
	}
	out, err := json.MarshalIndent(job, "", "  ")
	if err != nil {
		fmt.Printf("job %s: %s\n", job.JobID, job.Status)
		return 0
	}
	fmt.Println(string(out))
	return 0
}
