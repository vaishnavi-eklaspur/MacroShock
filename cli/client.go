package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Client talks to the MacroShock compute API.
type Client struct {
	BaseURL string
	APIKey  string
	HTTP    *http.Client
}

// Job is the API's job record. Mode distinguishes a genuinely queued run from the in-process
// fallback, so the CLI never claims work was distributed when it was not.
type Job struct {
	JobID     string         `json:"job_id"`
	Status    string         `json:"status"`
	Mode      string         `json:"mode"`
	Error     string         `json:"error,omitempty"`
	Note      string         `json:"note,omitempty"`
	Result    map[string]any `json:"result,omitempty"`
	Submitted string         `json:"submitted_utc,omitempty"`
}

func NewClient(baseURL, apiKey string) *Client {
	return &Client{
		BaseURL: strings.TrimRight(baseURL, "/"),
		APIKey:  apiKey,
		HTTP:    &http.Client{Timeout: 120 * time.Second},
	}
}

func (c *Client) request(method, path string, payload any) ([]byte, int, error) {
	var body io.Reader
	if payload != nil {
		encoded, err := json.Marshal(payload)
		if err != nil {
			return nil, 0, fmt.Errorf("encoding request: %w", err)
		}
		body = bytes.NewReader(encoded)
	}

	req, err := http.NewRequest(method, c.BaseURL+path, body)
	if err != nil {
		return nil, 0, fmt.Errorf("building request: %w", err)
	}
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.APIKey != "" {
		req.Header.Set("X-API-Key", c.APIKey)
	}

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, 0, fmt.Errorf("calling %s: %w", c.BaseURL+path, err)
	}
	defer resp.Body.Close()

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, resp.StatusCode, fmt.Errorf("reading response: %w", err)
	}
	return data, resp.StatusCode, nil
}

// apiError extracts the server's error message, falling back to a body excerpt when the response
// is not the JSON we expect (a proxy error page, say).
func apiError(status int, body []byte) error {
	var payload struct {
		Error string `json:"error"`
	}
	if err := json.Unmarshal(body, &payload); err == nil && payload.Error != "" {
		return fmt.Errorf("server returned %d: %s", status, payload.Error)
	}
	excerpt := strings.TrimSpace(string(body))
	if len(excerpt) > 200 {
		excerpt = excerpt[:200] + "..."
	}
	return fmt.Errorf("server returned %d: %s", status, excerpt)
}

// Submit forwards the original specification document for execution.
func (c *Client) Submit(rawSpec []byte) (*Job, error) {
	body, status, err := c.request(http.MethodPost, "/api/workflows",
		map[string]string{"spec_yaml": string(rawSpec)})
	if err != nil {
		return nil, err
	}
	if status != http.StatusAccepted && status != http.StatusOK {
		return nil, apiError(status, body)
	}
	var job Job
	if err := json.Unmarshal(body, &job); err != nil {
		return nil, fmt.Errorf("decoding job record: %w", err)
	}
	return &job, nil
}

// Status fetches the current state of a submitted job.
func (c *Client) Status(jobID string) (*Job, error) {
	body, status, err := c.request(http.MethodGet, "/api/jobs/"+jobID, nil)
	if err != nil {
		return nil, err
	}
	if status != http.StatusOK {
		return nil, apiError(status, body)
	}
	var job Job
	if err := json.Unmarshal(body, &job); err != nil {
		return nil, fmt.Errorf("decoding job record: %w", err)
	}
	return &job, nil
}

// Wait polls until the job reaches a terminal state or the deadline passes.
func (c *Client) Wait(jobID string, interval, timeout time.Duration) (*Job, error) {
	deadline := time.Now().Add(timeout)
	for {
		job, err := c.Status(jobID)
		if err != nil {
			return nil, err
		}
		if job.Status == "SUCCESS" || job.Status == "FAILURE" {
			return job, nil
		}
		if time.Now().After(deadline) {
			return job, fmt.Errorf("timed out after %s waiting for job %s (last status: %s)",
				timeout, jobID, job.Status)
		}
		time.Sleep(interval)
	}
}
