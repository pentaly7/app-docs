# State files

State is committed, so drift detection, resume and Docmost page IDs work on any machine that pulls the repo. There are two kinds of file, so parallel app agents never write the same file:

- `docs/.docgen/state.json`: global. Written **only by the orchestrator** (generate/update/sync skills).
- `docs/.docgen/apps/<app-id>.json`: one per app. Written **only by the app-documenter** working on that app.

Write JSON with 2-space indent and sorted keys, so git diffs stay small.

## `state.json`

```json
{
  "template_version": 2,
  "humanizer_version": 2,
  "diagram_version": 3,
  "split_all": false,
  "apps": {
    "payment-api": {
      "root": "services/payment-api",
      "language": "go",
      "kind": "backend",
      "fsm": false,
      "stage": "done",
      "stage_updated_at": "2026-11-15T07:30:00+07:00"
    }
  },
  "docmost": {
    "root_url": "https://docmost.example.com/s/engineering",
    "method": "paste-markdown",
    "diagram_theme": "adaptive",
    "pages": {
      "payment-api": { "url": "https://docmost.example.com/s/engineering/p/payment-api-x1y2" },
      "payment-api/operator-guide.md": {
        "url": "https://…",
        "content_hash": "sha256:…",
        "synced_sha": "a1b2c3d4…",
        "synced_at": "2026-11-15T08:00:00+07:00"
      }
    }
  }
}
```

- `kind`: `backend` | `frontend` | `worker` | `cli` | `library`.
- `stage` (per-app pipeline, used for resume): `pending` → `drafted` → `reviewed` → `fixed` → `done`. Also `failed`, with a `stage_error` string.
- `diagram_version`: the diagram rules the diagrams were last drawn with. When it differs from the plugin's, the next run redraws the diagrams only (text untouched).
- `apps.<id>.fsm`: state machine detection is on for this app. Set by running with `fsm`, kept for every later run.
- `docmost.diagram_theme`: `adaptive` (light and dark palette, default) or `light` (always light), decided by the first sync's calibration.
- `humanizer_version`: the humanizer rules the operator guides were last polished with. When it differs from the plugin's, the next run re-humanizes only.
- `split_all`: true when the repo has more than 10 apps (conventions §10).
- `docmost.pages` keys: the app ID for the app's container page; `<app-id>/operator` and `<app-id>/dev` for split-mode container pages; otherwise the doc file path relative to `docs/`. `docmost` stays `{}` until the first sync.

## `apps/<app-id>.json`

```json
{
  "app_id": "payment-api",
  "root": "services/payment-api",
  "language": "go",
  "framework": "gin",
  "kind": "backend",
  "split": false,
  "fsm": false,
  "state_machines": [],
  "docs": {
    "dev": "docs/payment-api/dev-guide.md",
    "operator": "docs/payment-api/operator-guide.md"
  },
  "flows": [
    {
      "id": "create-payment",
      "label": "POST /v1/payments",
      "kind": "http",
      "important": true,
      "entry": "services/payment-api/internal/handler/payment.go:42",
      "status": "active",
      "removed_in": null
    }
  ],
  "sections": {
    "dev:app-flow/create-payment": {
      "sha": "a1b2c3d4e5f6…(full)",
      "dirty": false,
      "branch": "main",
      "date": "2026-11-15",
      "verified_by": "Rizki Tegar",
      "files": [
        "services/payment-api/internal/handler/payment.go",
        "services/payment-api/internal/service/payment.go"
      ],
      "diagram": "drawio",
      "status": "active"
    }
  }
}
```

- In split mode, `docs.dev` and `docs.operator` are folders (`docs/payment-api/dev/`).
- `flows[].kind`: `http` | `grpc` | `consumer` | `cron` | `cli` | `page` | `other`.
- `flows[].label` must appear verbatim in both docs. The validator checks this.
- Section keys: `dev:<section-id>` or `op:<section-id>`, matching the anchors.
- `files`: every repo-root-relative file whose change could make this section wrong. Drift detection depends on this list, so be generous. For `setup`, include the build files, config loader, `.env.example`, Dockerfile and CI files. `glossary` may be empty, since it's refreshed whenever any other section in the doc changes.
- `diagram`: `drawio` | `mermaid` | `none`.
- `fsm` / `state_machines`: see `state-machines.md` §7.
- `status`: `active` | `removed`.
