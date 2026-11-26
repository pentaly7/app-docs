#!/usr/bin/env bash
# Builds the workspace at run time: git repos can't be committed inside the plugin's own repo.
set -eu
repo() {  # repo <dir> <name>
  mkdir -p "$1"
  git -C "$1" init -q -b main
  git -C "$1" config user.name "Jane Doe"
  git -C "$1" config user.email "jane@example.com"
  git -C "$1" remote add origin "git@gitlab.example.com:team/$2.git"
}
commit() { git -C "$1" add -A && git -C "$1" commit -q -m "$2"; }

repo db-service db-service
cat > db-service/go.mod <<'GO'
module example.com/db-service

go 1.22
GO
mkdir -p db-service/cmd/server db-service/internal/rows
cat > db-service/cmd/server/main.go <<'GO'
package main

import (
	"log/slog"
	"net/http"
	"os"

	"example.com/db-service/internal/rows"
)

func main() {
	h := rows.NewHandler(os.Getenv("DB_DSN"))
	http.HandleFunc("GET /rows/{id}", h.Get)
	http.HandleFunc("POST /rows", h.Insert)
	slog.Info("db-service listening", "addr", ":8081")
	if err := http.ListenAndServe(":8081", nil); err != nil {
		slog.Error("server stopped", "err", err)
		os.Exit(1)
	}
}
GO
cat > db-service/internal/rows/handler.go <<'GO'
package rows

import (
	"database/sql"
	"encoding/json"
	"log/slog"
	"net/http"
)

type Handler struct{ db *sql.DB }

func NewHandler(dsn string) *Handler {
	db, _ := sql.Open("postgres", dsn)
	return &Handler{db: db}
}

func (h *Handler) Get(w http.ResponseWriter, r *http.Request) {
	var balance int64
	err := h.db.QueryRowContext(r.Context(), "SELECT balance FROM wallet_balance WHERE member_id = $1", r.PathValue("id")).Scan(&balance)
	if err == sql.ErrNoRows {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	if err != nil {
		slog.Error("row read failed", "err", err)
		http.Error(w, "db error", http.StatusInternalServerError)
		return
	}
	json.NewEncoder(w).Encode(map[string]int64{"balance": balance})
}

func (h *Handler) Insert(w http.ResponseWriter, r *http.Request) {
	var in struct {
		MemberID string `json:"member_id"`
		Amount   int64  `json:"amount"`
	}
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil || in.MemberID == "" {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	if _, err := h.db.ExecContext(r.Context(), "UPDATE wallet_balance SET balance = balance + $1 WHERE member_id = $2", in.Amount, in.MemberID); err != nil {
		slog.Error("row write failed", "err", err)
		http.Error(w, "db error", http.StatusInternalServerError)
		return
	}
	slog.Info("balance updated", "member", in.MemberID)
	w.WriteHeader(http.StatusNoContent)
}
GO
printf 'DB_DSN=postgres://user:pass@localhost/wallet\n' > db-service/.env.example
commit db-service "db-service"

repo group/wallet wallet
cat > group/wallet/go.mod <<'GO'
module example.com/wallet

go 1.22
GO
mkdir -p group/wallet/cmd/wallet group/wallet/internal/credit
cat > group/wallet/cmd/wallet/main.go <<'GO'
package main

import (
	"log/slog"
	"net/http"
	"os"

	"example.com/wallet/internal/credit"
)

func main() {
	svc := credit.New(os.Getenv("DB_SERVICE_URL"))
	http.HandleFunc("POST /credit", svc.Credit)
	slog.Info("wallet listening", "addr", ":8080")
	if err := http.ListenAndServe(":8080", nil); err != nil {
		os.Exit(1)
	}
}
GO
cat > group/wallet/internal/credit/credit.go <<'GO'
package credit

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"net/http"
	"time"
)

type Service struct {
	dbURL  string
	client *http.Client
}

func New(dbURL string) *Service {
	return &Service{dbURL: dbURL, client: &http.Client{Timeout: 5 * time.Second}}
}

// Credit adds an amount to a member's balance through db-service.
func (s *Service) Credit(w http.ResponseWriter, r *http.Request) {
	var in struct {
		MemberID string `json:"member_id"`
		Amount   int64  `json:"amount"`
	}
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil || in.Amount <= 0 {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	body, _ := json.Marshal(in)
	resp, err := s.client.Post(s.dbURL+"/rows", "application/json", bytes.NewReader(body))
	if err != nil || resp.StatusCode != http.StatusNoContent {
		slog.Error("credit failed", "member", in.MemberID, "err", err)
		http.Error(w, "credit failed", http.StatusBadGateway)
		return
	}
	slog.Info("wallet credited", "member", in.MemberID, "amount", in.Amount)
	w.WriteHeader(http.StatusOK)
}
GO
printf 'DB_SERVICE_URL=http://db-service:8081\n' > group/wallet/.env.example
commit group/wallet "wallet"

repo shop shop
cat > shop/go.mod <<'GO'
module example.com/shop

go 1.22
GO
mkdir -p shop/cmd/shop shop/internal/order
cat > shop/cmd/shop/main.go <<'GO'
package main

import (
	"log/slog"
	"net/http"
	"os"

	"example.com/shop/internal/order"
)

func main() {
	h := order.New(os.Getenv("WALLET_URL"))
	http.HandleFunc("POST /refund", h.Refund)
	slog.Info("shop listening", "addr", ":8090")
	if err := http.ListenAndServe(":8090", nil); err != nil {
		os.Exit(1)
	}
}
GO
cat > shop/internal/order/refund.go <<'GO'
package order

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"net/http"
	"time"
)

type Handler struct {
	walletURL string
	client    *http.Client
}

func New(walletURL string) *Handler {
	return &Handler{walletURL: walletURL, client: &http.Client{Timeout: 3 * time.Second}}
}

// Refund pays an order's amount back into the member's wallet.
func (h *Handler) Refund(w http.ResponseWriter, r *http.Request) {
	var in struct {
		OrderID  string `json:"order_id"`
		MemberID string `json:"member_id"`
		Amount   int64  `json:"amount"`
	}
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil || in.OrderID == "" {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	body, _ := json.Marshal(map[string]any{"member_id": in.MemberID, "amount": in.Amount})
	for attempt := 1; attempt <= 2; attempt++ {
		resp, err := h.client.Post(h.walletURL+"/credit", "application/json", bytes.NewReader(body))
		if err == nil && resp.StatusCode == http.StatusOK {
			slog.Info("refund paid", "order", in.OrderID)
			w.WriteHeader(http.StatusOK)
			return
		}
		slog.Warn("wallet credit retry", "order", in.OrderID, "attempt", attempt)
	}
	slog.Error("refund failed", "order", in.OrderID)
	http.Error(w, "refund failed", http.StatusBadGateway)
}
GO
printf 'WALLET_URL=http://wallet:8080\n' > shop/.env.example
commit shop "shop"

# Not services: a nested clone inside shop, a vendored repo, and a repo too deep to count.
for extra in shop/third_party/lib vendor/somelib a/b/too-deep; do
  repo "$extra" "$(basename "$extra")"
  printf 'package lib\n' > "$extra/lib.go"
  commit "$extra" "lib"
done
