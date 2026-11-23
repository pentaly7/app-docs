package metrics

import (
	"fmt"
	"net/http"
	"sync"
)

var (
	mu      sync.Mutex
	redeems = map[string]int{}
	expired int
)

func RedeemResult(result string) {
	mu.Lock()
	redeems[result]++
	mu.Unlock()
}

func VouchersExpired(n int) {
	mu.Lock()
	expired += n
	mu.Unlock()
}

// Handler serves the counters in the Prometheus text format.
func Handler(w http.ResponseWriter, _ *http.Request) {
	mu.Lock()
	defer mu.Unlock()
	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	fmt.Fprintln(w, "# TYPE voucher_redeem_total counter")
	for result, n := range redeems {
		fmt.Fprintf(w, "voucher_redeem_total{result=%q} %d\n", result, n)
	}
	fmt.Fprintln(w, "# TYPE voucher_expired_total counter")
	fmt.Fprintf(w, "voucher_expired_total %d\n", expired)
}
