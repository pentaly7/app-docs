# State files

State is committed, so drift detection, resume and Docmost page IDs work on any machine that pulls the repo. There are two kinds of file, so parallel app agents never write the same file:

- `docs/.docgen/state.json`: global. Written **only by the orchestrator** (generate/update/sync skills).
- `docs/.docgen/apps/<app-id>.json`: one per app. Written **only by the app-documenter** working on that app.

Write JSON with 2-space indent and sorted keys, so git diffs stay small.

## `state.json`

```json
{
  "template_version": 4,
  "humanizer_version": 2,
  "diagram_version": 8,
  "story_version": 4,
  "split_all": false,
  "skills": {
    "humanizer-indonesia": { "sha256": "3f2a…", "commit": "9c1d2e3f4a" },
    "drawio": { "sha256": "b81c…", "commit": null }
  },
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
    "list_numbers": "native",
    "image_method": "clipboard-file",
    "pages": {
      "payment-api": {
        "url": "https://docmost.example.com/s/engineering/p/payment-api-x1y2",
        "content_hash": "sha256:…",
        "synced_sha": "a1b2c3d4…",
        "synced_at": "2026-11-15T08:00:00+07:00"
      }
    }
  }
}
```

- `kind`: `backend` | `frontend` | `worker` | `cli` | `library`.
- `stage`: `pending` (never documented), `working`, `failed` (with a `stage_error` string) or `done`. Only `done` apps are synced and get READMEs.
- `job`, `step`, `jobs`, `job_started`, `flows_todo`, `flows_done`: written by `pipeline.py` only, while an app has work (pipeline §5). They're what lets a cut-off run resume at the same step; they're removed when the app is `done`. 2.x stages (`app-done`, `drafted`, …) aren't continued: the next run asks to start those apps fresh.
- `flows_done`: important flows whose flow agent finished in the current pass (cleared when the app reaches `done`), so a resumed run starts only the missing ones.
- `diagram_version`: the diagram rules the diagrams were last drawn with. When it differs from the plugin's, the next run redraws the diagrams only (text untouched).
- `story_version`: the sequence-story rules the stories were last written with. When it differs from the plugin's, the next run re-reads the code and rewrites only the stories.
- `apps.<id>.fsm`: state machine detection is on for this app. Set by running with `fsm`, kept for every later run.
- `docmost.diagram_theme`: `adaptive` (default) or `light`, decided by the first sync's calibration. It only changes the copies sync uploads: the `.drawio.svg` files in `docs/` stay adaptive, because GitLab shows them too.
- `humanizer_version`: the humanizer rules the operator guides were last polished with. When it differs from the plugin's, the next run re-humanizes only.
- `split_all`: true when the repo has more than 10 apps (conventions §10).
- `docmost.pages` holds **User Guide pages only**; the Dev Guide is read in GitLab. Keys follow the doc's structure, not its file paths, so splitting a doc or renaming a file keeps the same Docmost page (and its URL, history and comments):
  - `<app-id>`: the app's page. Its body is the User Guide (single mode) or the User Guide's top `00-index.md` (split mode; empty without one).
  - `<app-id>/op/<first-anchor-id>`: one split-mode file, keyed by the first section anchor in it, under the app page.
  `docs_tool.py migrate` converts keys from plugin versions before 2.9 (file paths) and drops `<app-id>/dev…` keys from 2.x without touching Docmost. `docmost` stays `{}` until the first sync.
- Inside a workspace, `root_url`, `method`, `image_method`, `diagram_theme`, `list_numbers` and `image_reuse` are also kept in the workspace file (`pipeline.md` §8), and the workspace's values win: one calibration serves every repo synced to that Docmost. Each repo keeps its own copy, so a sync from that repo alone still works.
- `docmost.list_numbers`: `native` or `bold` (calibration found Docmost renumbers lists, so numbers are written as `**5.**`).
- `docmost.image_method`: how diagrams got into pages last time: `clipboard-file`, `file-upload` or `paste-script` (sync skill).
- `skills`: the version of each outside skill used by the last run (`docs_tool.py skill-pin`), so a changed humanizer or draw.io skill is reported.

## `apps/<app-id>.json`

```json
{
  "app_id": "payment-api",
  "template_version": 4,
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
      "run_by": "Jane Doe",
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
- `flows[].external`: the flow calls another system (diagrams §1); only then does it get a sequence diagram and story. Missing means true (docs from before 2.10.2).
- `flows[].group`: flows documented by one flow agent together because they share most of their code. Missing means one group for all.
- `stage_at`: when `stage` last changed, written by `docs_tool.py stage`.
- `docmost.images`: content hash of each uploaded diagram → `{url, page, name}`, so other pages link to the upload instead of uploading again. Dropped when that page is archived or deleted. `docmost.image_reuse`: `off` when calibration found links to another page's image don't show.
- `flows[].subflows_owned` / `subflows_used`: shared sub-flow ids (`shared.<sub-id>` diagrams). Exactly one important flow owns each; its agent draws it.
- `flows[].label` must appear verbatim in both docs. The validator checks this.
- Section keys: `dev:<section-id>` or `op:<section-id>`, matching the anchors.
- `blobs` / `blobs_at`: written by `docs_tool.py stamp`, never by agents. The git blob id of each file in `files` at the section's commit, so drift compares file contents and still works after a squash merge or rebase removes the commit.
- `template_version` (app state, top level): the template this app's docs follow. Apps can differ during an upgrade; `state.json → template_version` is the lowest.
- `files`: every repo-root-relative file whose change could make this section wrong. Drift detection depends on this list, so be generous. For `setup`, include the build files, config loader, `.env.example`, Dockerfile and CI files. `glossary` may be empty, since it's refreshed whenever any other section in the doc changes.
- `diagram`: `drawio` | `mermaid` | `none`.
- `fsm` / `state_machines`: see `state-machines.md` §7.
- `status`: `active` | `removed`.
