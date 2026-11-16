---
name: sync
description: One-way sync of the app docs in /docs to Docmost (community edition, no API) by driving the user's logged-in Chrome through Claude in Chrome. Creates the Space › App › Operator Guide / Dev Doc page tree the first time, then updates the same pages in place on later runs, so URLs stay stable. Pass the Docmost space or parent-page URL on the first run; it's saved for later runs.
argument-hint: "[docmost-url]"
disable-model-invocation: true
---

# Sync docs to Docmost

Arguments: `$ARGUMENTS`

Docmost community edition has no API keys or MCP here, so this drives the Docmost web UI in the user's Chrome. Sync is **one-way**: the repo is the source of truth, and edits made in Docmost are overwritten on the next sync. Pages are updated **in place**, so URLs, links and comments survive. Pages are never deleted, because removed flows stay in the docs with a Removed mark.

`TOOL` = `python3 <this skill's base directory>/../../shared/scripts/docs_tool.py`. `REPO` = `git rev-parse --show-toplevel`.

## 1. Plan

1. `docs/.docgen/state.json` missing → tell the user to run `/app-docs:generate` first, and stop.
2. URL: if the arguments contain a URL, save it with `TOOL sync-record --repo REPO --root-url <url>`. If none was given and state has no `docmost.root_url`, ask for the Docmost space (or parent page) URL, and stop until they answer.
3. Run `TOOL sync-plan --repo REPO`. It lists every page in parent-before-child order, with:
   - `key`, `parent` (a key or null, where null means directly under the root URL), `title`, `existing_url`, `changed`
   - for content pages: `paste_js` (a ready-made browser script that sets the title and body and uploads diagrams) and `content_hash`
   - container pages (an app page, "Operator Guide"/"Dev Doc" in split mode) have no `paste_js`. Create them with just the title.
   Only apps at stage `done` are included.
4. `to_sync` is 0 → say "Docmost is up to date" and stop. Otherwise tell the user how many pages will be created or updated, and that Chrome must stay open and logged in to Docmost.

## 2. Open Chrome

If a `chrome-browser` skill is listed, load it first. Load the browser tools in **one** ToolSearch call:
`select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__find,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__get_page_text`

If the tools don't exist or can't reach Chrome, say that sync needs Claude Code running locally with Chrome and the Claude in Chrome extension connected (`claude --chrome`, or the desktop app), and stop.

Call `tabs_context_mcp`, open a **new** tab, and navigate to `root_url`. If Docmost shows a login page, ask the user to log in in that tab and tell you when done.

Avoid anything that opens a browser dialog (delete, "leave page?" confirmations). Dialogs block the extension.

## 3. Calibrate (first sync, or when `docmost.method` is null)

The paste script assumes two things about this Docmost version: pasted Markdown is converted to rich content, and a pasted SVG file is uploaded as an image. Prove both on the **first content page** before syncing the rest:

1. Create or open that page (section 4), run its `paste_js` with `javascript_tool`, and read the JSON it returns.
2. Check:
   - `literal_markdown` is false (headings and tables were converted, not shown as raw text)
   - `leftover_placeholders` is 0
   - every image is `pasted`, and `img_elements` ≥ the number of images
   - a screenshot shows Mermaid blocks rendered as diagrams
3. All good → `TOOL sync-record --repo REPO --method paste-markdown`, record the page (section 4, step 4), and continue.
4. Anything failed → stop. Show the user the screenshot and what failed. Don't improvise another method that might change URLs or lose content. The usual fixes are a newer Docmost version (Markdown paste) or exporting diagrams as PNG. Decide with the user.

## 4. Sync each page with `changed: true`, in plan order

1. **Find or create the page**
   - `existing_url` set → navigate to it. If it's gone (404), treat the page as new.
   - New → open the parent page (its URL from state, or `root_url` for `parent: null`). Create a child page with Docmost's "add subpage" control. Use `find`/`read_page` to locate it, since UI labels vary by version. Wait until the new page's editor shows.
2. **Write content**
   - Container page: type the title into the title field, then leave the body empty.
   - Content page: Read the page's `paste_js` file and pass its full contents to `javascript_tool`. Check the returned JSON as in calibration (`ok`, `literal_markdown`, `leftover_placeholders`, images).
3. Wait about 3 seconds for Docmost to autosave, then check the page text once with `get_page_text`.
4. **Record immediately**, so a failure halfway through doesn't lose the mapping:
   `TOOL sync-record --repo REPO --key <key> --url <current page URL> [--content-hash <content_hash>]`
   (no `--content-hash` for container pages).
5. On failure: record nothing for that page, note it, and continue with the next page. Skip the children of a page that failed to create.

## 5. Report

Pages created, updated, unchanged and failed (with reason), plus the Docmost URL of each app page. `sync-record` changed `docs/.docgen/state.json`, so remind the user to commit it. That's what lets the next sync, from any machine, update the same pages instead of creating duplicates.
