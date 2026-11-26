/app-docs:generate

Input files: a parent folder (the working directory) with three service repos built by place-files.sh: `db-service/`, `group/wallet/` and `shop/`. shop calls wallet (`WALLET_URL`), wallet calls db-service (`DB_SERVICE_URL`). Also present and not services: `shop/third_party/lib` (a nested clone), `vendor/somelib` and `a/b/too-deep`.
