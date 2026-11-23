package voucher

import (
	"context"
	"errors"
	"testing"
	"time"

	"example.com/voucher-api/internal/store"
)

type fakeWallet struct{ err error }

func (f fakeWallet) Credit(context.Context, string, string, int64) error { return f.err }

func newService(t *testing.T, w Crediter) (*Service, *store.Store) {
	t.Helper()
	st, err := store.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	st.Put(store.Voucher{Code: "A1", Amount: 50000, Status: store.Issued, ExpiresAt: time.Now().Add(time.Hour)})
	return NewService(st, w), st
}

func TestRedeemTwice(t *testing.T) {
	svc, _ := newService(t, fakeWallet{})
	if _, err := svc.Redeem(context.Background(), "A1", "m1"); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.Redeem(context.Background(), "A1", "m1"); !errors.Is(err, ErrAlreadyRedeemed) {
		t.Fatalf("got %v", err)
	}
}

func TestWalletFailureReleasesVoucher(t *testing.T) {
	svc, st := newService(t, fakeWallet{err: errors.New("down")})
	svc.Redeem(context.Background(), "A1", "m1")
	if v, _ := st.Get("A1"); v.Status != store.Issued {
		t.Fatalf("status %s", v.Status)
	}
}

func TestExpireDue(t *testing.T) {
	svc, st := newService(t, fakeWallet{})
	svc.now = func() time.Time { return time.Now().Add(2 * time.Hour) }
	if n := svc.ExpireDue(); n != 1 {
		t.Fatalf("expired %d", n)
	}
	if v, _ := st.Get("A1"); v.Status != store.Expired {
		t.Fatalf("status %s", v.Status)
	}
}
