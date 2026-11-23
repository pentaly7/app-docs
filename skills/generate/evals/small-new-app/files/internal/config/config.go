package config

import (
	"fmt"
	"os"
	"strconv"
	"time"
)

type Config struct {
	Port           string
	DataDir        string
	WalletURL      string
	WalletAPIKey   string
	WalletTimeout  time.Duration
	WalletRetries  int
	ExpiryInterval time.Duration
}

// Load reads the environment. WALLET_URL and WALLET_API_KEY are required: the service
// can't redeem anything without the wallet, so it refuses to start instead of failing later.
func Load() (Config, error) {
	cfg := Config{
		Port:      getenv("PORT", "8080"),
		DataDir:   getenv("DATA_DIR", "./data"),
		WalletURL: os.Getenv("WALLET_URL"),
	}
	cfg.WalletAPIKey = os.Getenv("WALLET_API_KEY")
	if cfg.WalletURL == "" || cfg.WalletAPIKey == "" {
		return cfg, fmt.Errorf("config: WALLET_URL and WALLET_API_KEY are required")
	}
	ms, err := strconv.Atoi(getenv("WALLET_TIMEOUT_MS", "3000"))
	if err != nil {
		return cfg, fmt.Errorf("config: WALLET_TIMEOUT_MS: %w", err)
	}
	cfg.WalletTimeout = time.Duration(ms) * time.Millisecond
	if cfg.WalletRetries, err = strconv.Atoi(getenv("WALLET_RETRIES", "2")); err != nil {
		return cfg, fmt.Errorf("config: WALLET_RETRIES: %w", err)
	}
	if cfg.ExpiryInterval, err = time.ParseDuration(getenv("EXPIRY_INTERVAL", "5m")); err != nil {
		return cfg, fmt.Errorf("config: EXPIRY_INTERVAL: %w", err)
	}
	return cfg, nil
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
