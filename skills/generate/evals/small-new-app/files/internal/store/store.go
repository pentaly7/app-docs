package store

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type Status string

const (
	Issued   Status = "ISSUED"
	Pending  Status = "PENDING"
	Redeemed Status = "REDEEMED"
	Expired  Status = "EXPIRED"
)

type Voucher struct {
	Code       string    `json:"code"`
	Amount     int64     `json:"amount"`
	Status     Status    `json:"status"`
	ExpiresAt  time.Time `json:"expires_at"`
	RedeemedBy string    `json:"redeemed_by,omitempty"`
	UpdatedAt  time.Time `json:"updated_at"`
}

var ErrNotFound = errors.New("voucher not found")

// Store keeps every voucher in one JSON file, vouchers.json in the data dir.
// Every write rewrites the file through a temp file and a rename, so a crash never leaves half a file.
type Store struct {
	mu       sync.Mutex
	path     string
	vouchers map[string]*Voucher
}

func Open(dataDir string) (*Store, error) {
	if err := os.MkdirAll(dataDir, 0o755); err != nil {
		return nil, err
	}
	s := &Store{path: filepath.Join(dataDir, "vouchers.json"), vouchers: map[string]*Voucher{}}
	raw, err := os.ReadFile(s.path)
	if errors.Is(err, os.ErrNotExist) {
		return s, nil
	}
	if err != nil {
		return nil, err
	}
	var list []*Voucher
	if err := json.Unmarshal(raw, &list); err != nil {
		return nil, err
	}
	for _, v := range list {
		s.vouchers[v.Code] = v
	}
	return s, nil
}

func (s *Store) Get(code string) (Voucher, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	v, ok := s.vouchers[code]
	if !ok {
		return Voucher{}, ErrNotFound
	}
	return *v, nil
}

// Update applies change to one voucher under the store lock and persists it. change returns
// an error to abort without writing.
func (s *Store) Update(code string, change func(*Voucher) error) (Voucher, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	v, ok := s.vouchers[code]
	if !ok {
		return Voucher{}, ErrNotFound
	}
	next := *v
	if err := change(&next); err != nil {
		return *v, err
	}
	next.UpdatedAt = time.Now().UTC()
	s.vouchers[code] = &next
	if err := s.flush(); err != nil {
		s.vouchers[code] = v
		return *v, err
	}
	return next, nil
}

func (s *Store) Put(v Voucher) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	v.UpdatedAt = time.Now().UTC()
	s.vouchers[v.Code] = &v
	return s.flush()
}

func (s *Store) Codes() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]string, 0, len(s.vouchers))
	for code := range s.vouchers {
		out = append(out, code)
	}
	return out
}

func (s *Store) flush() error {
	list := make([]*Voucher, 0, len(s.vouchers))
	for _, v := range s.vouchers {
		list = append(list, v)
	}
	raw, err := json.MarshalIndent(list, "", "  ")
	if err != nil {
		return err
	}
	tmp := s.path + ".tmp"
	if err := os.WriteFile(tmp, raw, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, s.path)
}
