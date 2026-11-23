package voucher

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"example.com/voucher-api/internal/metrics"
	"example.com/voucher-api/internal/store"
	"example.com/voucher-api/internal/wallet"
)

var (
	ErrAlreadyRedeemed = errors.New("voucher already redeemed")
	ErrExpired         = errors.New("voucher expired")
	ErrInProgress      = errors.New("voucher redemption in progress")
)

type Crediter interface {
	Credit(ctx context.Context, memberID, voucherCode string, amount int64) error
}

type Service struct {
	store  *store.Store
	wallet Crediter
	now    func() time.Time
}

func NewService(s *store.Store, w Crediter) *Service {
	return &Service{store: s, wallet: w, now: time.Now}
}

// Redeem moves a voucher ISSUED → PENDING, credits the wallet, then PENDING → REDEEMED.
// When the wallet fails the voucher goes back to ISSUED, so the member can try again.
func (s *Service) Redeem(ctx context.Context, code, memberID string) (store.Voucher, error) {
	v, err := s.store.Update(code, func(v *store.Voucher) error {
		switch {
		case v.Status == store.Redeemed:
			return ErrAlreadyRedeemed
		case v.Status == store.Expired || s.now().After(v.ExpiresAt):
			return ErrExpired
		case v.Status == store.Pending:
			return ErrInProgress
		}
		v.Status = store.Pending
		return nil
	})
	if err != nil {
		metrics.RedeemResult(resultOf(err))
		return v, err
	}

	if err := s.wallet.Credit(ctx, memberID, code, v.Amount); err != nil {
		slog.Error("wallet credit failed, voucher released", "code", code, "error", err)
		if _, rerr := s.store.Update(code, func(v *store.Voucher) error { v.Status = store.Issued; return nil }); rerr != nil {
			slog.Error("voucher stuck in PENDING", "code", code, "error", rerr)
		}
		metrics.RedeemResult(resultOf(err))
		return v, err
	}

	v, err = s.store.Update(code, func(v *store.Voucher) error {
		v.Status = store.Redeemed
		v.RedeemedBy = memberID
		return nil
	})
	if err != nil {
		slog.Error("voucher stuck in PENDING", "code", code, "error", err)
		return v, err
	}
	slog.Info("voucher redeemed", "code", code, "member_id", memberID, "amount", v.Amount)
	metrics.RedeemResult("ok")
	return v, nil
}

// ExpireDue marks every ISSUED voucher past its expiry as EXPIRED. PENDING ones are left alone:
// their wallet call decides.
func (s *Service) ExpireDue() int {
	count := 0
	for _, code := range s.store.Codes() {
		_, err := s.store.Update(code, func(v *store.Voucher) error {
			if v.Status != store.Issued || !s.now().After(v.ExpiresAt) {
				return errSkip
			}
			v.Status = store.Expired
			return nil
		})
		if err == nil {
			count++
		}
	}
	if count > 0 {
		slog.Info("vouchers expired", "count", count)
	}
	metrics.VouchersExpired(count)
	return count
}

var errSkip = errors.New("skip")

func resultOf(err error) string {
	switch {
	case errors.Is(err, store.ErrNotFound):
		return "not_found"
	case errors.Is(err, ErrAlreadyRedeemed):
		return "already_redeemed"
	case errors.Is(err, ErrExpired):
		return "expired"
	case errors.Is(err, ErrInProgress):
		return "in_progress"
	case errors.Is(err, wallet.ErrRejected):
		return "wallet_rejected"
	default:
		return "wallet_unavailable"
	}
}
