# voucher-api

Redeems reward vouchers into a member's wallet.

- `POST /v1/vouchers/{code}/redeem` with `{"member_id": "..."}`
- `GET /v1/vouchers/{code}`

Vouchers are stored in a Postgres table `vouchers`.

Run: copy `.env.example` to `.env`, fill in the wallet key, then `go run ./cmd/server`.
