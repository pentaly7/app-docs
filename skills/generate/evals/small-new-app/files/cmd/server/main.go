package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"example.com/voucher-api/internal/config"
	"example.com/voucher-api/internal/httpapi"
	"example.com/voucher-api/internal/store"
	"example.com/voucher-api/internal/voucher"
	"example.com/voucher-api/internal/wallet"
)

func main() {
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))

	cfg, err := config.Load()
	if err != nil {
		slog.Error("startup failed", "error", err)
		os.Exit(1)
	}
	st, err := store.Open(cfg.DataDir)
	if err != nil {
		slog.Error("startup failed: cannot open data dir", "dir", cfg.DataDir, "error", err)
		os.Exit(1)
	}
	svc := voucher.NewService(st, wallet.New(cfg.WalletURL, cfg.WalletAPIKey, cfg.WalletTimeout, cfg.WalletRetries))

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	go func() {
		ticker := time.NewTicker(cfg.ExpiryInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				svc.ExpireDue()
			}
		}
	}()

	srv := &http.Server{Addr: ":" + cfg.Port, Handler: httpapi.Routes(svc, st), ReadHeaderTimeout: 5 * time.Second}
	go func() {
		slog.Info("listening", "port", cfg.Port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("server stopped", "error", err)
			stop()
		}
	}()

	<-ctx.Done()
	shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	srv.Shutdown(shutdown)
	slog.Info("shut down")
}
