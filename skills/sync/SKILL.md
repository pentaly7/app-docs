---
name: sync
description: One-way sync of the User Guides in /docs to Docmost (community edition, no API) through the user's logged-in Chrome, for the current repo or every repo of a workspace folder. Each app's page is its User Guide; split guides hang their pages under it. The Dev Guide stays in GitLab. Pages are created the first time and updated in place later, so URLs stay stable. One sync agent per app, one at a time, callees first; links between services become Docmost links once their target page exists. Pass the Docmost space or parent-page URL on the first run; it's saved for later runs.
argument-hint: "[docmost-url]"
disable-model-invocation: true
model: sonnet
---

# Sync User Guides to Docmost

Arguments: `$ARGUMENTS`

Docmost community edition has no API keys or MCP here, so sync drives the Docmost web UI in the user's Chrome. Sync is **one-way**: the markdown in GitLab is the source of truth. Only User Guides are synced; developers read the Dev Guide in GitLab.

Run it in its **own conversation**, not right after a generate or update. If this conversation already holds a generate or update run, say so and suggest a new one; go on only if the user wants to.

Each app is synced by its own `docmost-syncer` agent, so the browser calls of one app never weigh on the next. They run **one at a time**: page text goes through the one OS clipboard and a real paste into the focused tab.

`PIPE` = `python3 <this skill's base directory>/../../shared/scripts/pipeline.py`. `TOOL` = `python3 <this skill's base directory>/../../shared/scripts/docs_tool.py`. `SHARED` = `<this skill's base directory>/../../shared`, as an absolute path.

## 1. Plan

1. `PIPE targets` from the folder the user is in. It lists the repos (callees first in a workspace) and, per app, the pages to create or update, links waiting for their target, orphans, and whether Docmost is calibrated. No page text: keep it that way.
   - A repo with `skip` → mention it. With `error` (two files map to the same page) → tell the user to fix that repo's docs first (validate reports `anchor-duplicate`): syncing would overwrite one page with the other's text. `not_done` apps aren't synced; mention them.
2. Root URL: a URL in the arguments → save it with `TOOL sync-record --repo <first repo> --root-url <url>` (in a workspace it's saved for every repo). No URL in the arguments and `root_url` is null → ask for the Docmost space or parent-page URL and stop until they answer.
3. `to_sync` is 0 and there are no orphans → "Docmost is up to date", and stop. Otherwise say how many pages will be created or updated, in how many apps, and that Chrome must stay open and logged in to Docmost.
4. **First sync only:** tell the user once that each sync replaces whole page bodies: edits made in Docmost are overwritten, and inline comments (attached to text) are lost or detached. Notes belong in their own Docmost pages, or in a merge request on the markdown. `<!-- app-docs:keep -->` text is synced like any other text.

## 2. Check the login, once

Load the `chrome-browser` skill if it's listed, then the browser tools in one ToolSearch call (`tabs_context_mcp`, `tabs_create_mcp`, `navigate`, `get_page_text`, `tabs_close_mcp`). No tools, or they can't reach Chrome → say that sync needs Claude Code running locally with Chrome and the Claude in Chrome extension connected (`claude --chrome`, or the desktop app), and stop.

Open a new tab on the root URL. A login page → ask the user to log in in that tab and say when done. Then close the tab.

## 3. Sync each app

For each repo in `targets` order, each app with `to_sync` above 0, launch **one** `docmost-syncer` agent and wait for it (not in the background: the next one needs the clipboard). Prompt:

```
Repo root: <repo>
Shared folder: <SHARED>
App: <app id>
Docmost root URL: <root_url>
Calibrated: <yes | no: calibrate on this app's first page with a diagram>
Checks still to do: <targets' `checks`>
```

Calibration and the checks go to the first syncer. After each syncer returns, run `PIPE targets` again: what it recorded is saved (in a workspace, for every repo), so the next prompt carries only what's still open.

When a syncer returns:
- `NEEDS USER: log in to Docmost` → ask the user to log in, then launch it again.
- `NEEDS USER: calibration failed` → show the user what it tried and its screenshot, and decide with them. Don't sync further apps until it's settled.
- `NEEDS USER: Chrome tools aren't reachable from a sync agent` → sync agents can't use Chrome in this setup. Do the syncs yourself instead, following `agents/docmost-syncer.md` (in the plugin folder, beside `skills/`), one app at a time, and tell the user once that this conversation carries every app's browser calls.
- Pages failed → note them for the report and go on with the next app.

## 4. Links that waited

`PIPE targets` once more. Pages linking to an app synced later in this run are `changed` now (their links resolve). Apps with `to_sync` above 0 get one more syncer each. Links still pending after that point at apps not documented or not synced yet; they become links on a later sync.

## 5. Orphans

Pages synced before whose doc no longer exists (an app left the repo, a split changed). Ask with **one** AskUserQuestion for all of them, listing each URL:
- **Archive**: rename the page to `[Archived] <its current title>` and move it under a page titled `Archive` directly under the root URL (create it once if it's missing). Docmost's move is in the page menu; find it with `find`. Do this yourself in one tab.
- **Delete**: deleting opens a confirmation dialog, which would block the extension. Open each page, point at Docmost's delete item in the page menu, and ask the user to click it and confirm. Wait until they say it's done.

After either one, `TOOL sync-record --repo <its repo> --remove-key <key>`. Neither → leave them; they're asked about again next time.

## 6. Report

Per repo and app: pages created, updated, unchanged, failed (with reason), archived and deleted; links still waiting; the Docmost URL of each app page; the image method. `sync-record` changed each synced repo's `docs/.docgen/state.json`, so remind the user to commit it in each repo: that's what lets the next sync, from any machine, update the same pages instead of creating duplicates. The workspace file in the parent folder isn't committed anywhere; losing it only means the next sync calibrates again.
