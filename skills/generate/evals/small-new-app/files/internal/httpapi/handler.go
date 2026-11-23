package httpapi

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"

	"example.com/voucher-api/internal/metrics"
	"example.com/voucher-api/internal/store"
	"example.com/voucher-api/internal/voucher"
	"example.com/voucher-api/internal/wallet"
)

func Routes(svc *voucher.Service, st *store.Store) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/vouchers/{code}/redeem", redeem(svc))
	mux.HandleFunc("GET /v1/vouchers/{code}", get(st))
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) })
	mux.HandleFunc("GET /metrics", metrics.Handler)
	return mux
}

type redeemRequest struct {
	MemberID string `json:"member_id"`
}

func redeem(svc *voucher.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req redeemRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.MemberID == "" {
			slog.Warn("invalid redeem request", "error", err)
			writeError(w, http.StatusBadRequest, "member_id required")
			return
		}
		v, err := svc.Redeem(r.Context(), r.PathValue("code"), req.MemberID)
		switch {
		case err == nil:
			writeJSON(w, http.StatusOK, v)
		case errors.Is(err, store.ErrNotFound):
			writeError(w, http.StatusNotFound, "voucher not found")
		case errors.Is(err, voucher.ErrAlreadyRedeemed), errors.Is(err, voucher.ErrInProgress):
			writeError(w, http.StatusConflict, err.Error())
		case errors.Is(err, voucher.ErrExpired):
			writeError(w, http.StatusGone, "voucher expired")
		case errors.Is(err, wallet.ErrRejected):
			writeError(w, http.StatusUnprocessableEntity, "wallet rejected the credit")
		default:
			writeError(w, http.StatusBadGateway, "wallet unavailable, try again")
		}
	}
}

func get(st *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		v, err := st.Get(r.PathValue("code"))
		if err != nil {
			writeError(w, http.StatusNotFound, "voucher not found")
			return
		}
		writeJSON(w, http.StatusOK, v)
	}
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}
