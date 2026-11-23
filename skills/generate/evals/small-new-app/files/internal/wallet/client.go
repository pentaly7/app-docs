package wallet

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"time"
)

var ErrUnavailable = errors.New("wallet unavailable")
var ErrRejected = errors.New("wallet rejected the credit")

type Client struct {
	baseURL string
	apiKey  string
	retries int
	http    *http.Client
}

func New(baseURL, apiKey string, timeout time.Duration, retries int) *Client {
	return &Client{baseURL: baseURL, apiKey: apiKey, retries: retries, http: &http.Client{Timeout: timeout}}
}

// Credit adds amount to the member's wallet. The voucher code is the idempotency key, so a retry
// after a timeout can't credit twice. 5xx and timeouts are retried; 4xx is final.
func (c *Client) Credit(ctx context.Context, memberID, voucherCode string, amount int64) error {
	body, _ := json.Marshal(map[string]any{"member_id": memberID, "amount": amount, "reference": voucherCode})
	var lastErr error
	for attempt := 0; attempt <= c.retries; attempt++ {
		if attempt > 0 {
			time.Sleep(time.Duration(attempt) * 500 * time.Millisecond)
		}
		req, _ := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/v1/credits", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-Api-Key", c.apiKey)
		req.Header.Set("Idempotency-Key", voucherCode)
		resp, err := c.http.Do(req)
		if err != nil {
			lastErr = err
			slog.Warn("wallet call failed", "attempt", attempt+1, "error", err)
			continue
		}
		resp.Body.Close()
		switch {
		case resp.StatusCode < 300:
			return nil
		case resp.StatusCode >= 500:
			lastErr = fmt.Errorf("status %d", resp.StatusCode)
			slog.Warn("wallet call failed", "attempt", attempt+1, "status", resp.StatusCode)
		default:
			return fmt.Errorf("%w: status %d", ErrRejected, resp.StatusCode)
		}
	}
	return fmt.Errorf("%w: %v", ErrUnavailable, lastErr)
}
