---
name: sync
description: One-way sync of the app docs in /docs to Docmost (community edition, no API) by driving the user's logged-in Chrome through Claude in Chrome. Creates the Space › App › User Guide / Dev Guide page tree the first time, then updates the same pages in place on later runs, so URLs stay stable. Asks whether to archive or delete pages that no longer have a doc. Pass the Docmost space or parent-page URL on the first run; it's saved for later runs.
argument-hint: "[docmost-url]"
disable-model-invocation: true
---

# Sync docs to Docmost

Arguments: `$ARGUMENTS`

Docmost community edition has no API keys or MCP here, so this drives the Docmost web UI in the user's Chrome. Sync is **one-way**: the markdown in GitLab is the source of truth.

What a sync keeps and what it replaces:
- **Kept:** each page's URL, its place in the tree, its page history, and page-level comments.
- **Replaced:** the whole body. Edits made in Docmost are overwritten. **Inline comments** (comments attached to a piece of text) are attached to text that the sync replaces, so they are lost or end up detached. Tell the user this before the first sync: notes belong in their own Docmost pages, or in a merge request on the markdown.
- Nothing is filtered or checked here: what is in the markdown in GitLab is what gets synced, validator failures included. Look at the last run's validator failures before you sync.
- `<!-- app-docs:keep -->` markers are removed; the text inside them is synced like any other text.

`TOOL` = `python3 <this skill's base directory>/../../shared/scripts/docs_tool.py`. `REPO` = `git rev-parse --show-toplevel`.

## 1. Plan

1. `docs/.docgen/state.json` missing → tell the user to run `/app-docs:generate` first, and stop.
2. URL: if the arguments contain a URL, save it with `TOOL sync-record --repo REPO --root-url <url>`. If none was given and state has no `docmost.root_url`, ask for the Docmost space (or parent page) URL, and stop until they answer.
3. Run `TOOL migrate --repo REPO` (it also converts page keys from older versions, so existing pages are found again), then `TOOL sync-plan --repo REPO`. It lists every page in parent-before-child order, with:
   - `key`, `parent` (a key, or null for directly under the root URL), `title`, `existing_url`, `changed`, `content_hash` (covers the title too, so a renamed page counts as changed)
   - `container: true` for pages with no body of their own (the app page; "User Guide"/"Dev Guide" in split mode)
   - `prepared_file`: the page body as markdown, diagrams replaced by `[[diagram:<name>]]` placeholders
   - `prepare_js`: sets the title and selects the whole body, ready for a paste
   - `check_js`: reports what the body holds now (headings, images uploaded, placeholders left, raw markdown showing)
   - `images[]`: per diagram `name`, `path`, `place_js` (selects and deletes its placeholder, leaving the cursor there) and `image_js` (fallback only)
   - `paste_text_js`: sets title and body by script, text only (fallback when the clipboard paste doesn't work; images still go by file upload)
   - `paste_js`: the same with every diagram as base64 (last resort: the diagrams pass through the conversation)
   - `orphans[]`: pages synced before whose doc no longer exists
   Titles: only the app's own page carries the app name. Use `title` exactly as given. Only apps at stage `done` are included.
   An `error` about two files mapping to the same page → stop and tell the user: two doc files carry the same first section (validate reports `anchor-duplicate`). Syncing would overwrite one page with the other's text.
4. `to_sync` is 0 and `orphans` is empty → say "Docmost is up to date" and stop. Otherwise say how many pages will be created or updated, and that Chrome must stay open and logged in to Docmost.

## 2. Open Chrome

If a `chrome-browser` skill is listed, load it first. Load the browser tools in **one** ToolSearch call:
`select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__find,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__get_page_text,mcp__claude-in-chrome__file_upload`

If the tools don't exist or can't reach Chrome, say that sync needs Claude Code running locally with Chrome and the Claude in Chrome extension connected (`claude --chrome`, or the desktop app), and stop.

Call `tabs_context_mcp`, open a **new** tab, and navigate to `root_url`. If Docmost shows a login page, ask the user to log in in that tab and tell you when done.

Avoid anything that opens a browser dialog (delete, "leave page?" confirmations). Dialogs block the extension.

## 3. How content gets into a page

Page text goes through the **OS clipboard**, not through you: `TOOL clip <prepared_file>` copies it, and a real keystroke pastes it. That keeps long pages out of the conversation and makes Docmost's own paste handler convert the markdown, exactly as when a person pastes.

**Write one page:**
1. Run its `prepare_js` with `javascript_tool`. `ok: false` → the editor isn't ready; wait 2 seconds and try once more.
2. `TOOL clip <prepared_file>`, then press `cmd+v` (macOS) or `ctrl+v` (others) with `computer` → `key`.
3. **Poll, don't sleep:** run `check_js` every 2 seconds, up to 15 times, until `literal_markdown` is false, `headings` has reached the plan's count, and `placeholders` equals the page's number of images. Timeout → the page failed.
4. For each image, in order: run its `place_js`, then insert the file with the recorded `docmost.image_method`:
   - `file-upload`: open Docmost's image insert at the cursor (type `/image` and choose the upload item; find it with `find`, labels vary by version), then `file_upload` with the image `path` on the file input it opens.
   - `clipboard-file`: `TOOL clip <path> --file-ref`, then paste with the keystroke.
   - `paste-script`: run its `image_js`. This sends the image through the conversation, so it's the last resort.
   Poll `check_js` until `images_uploaded` grew by one (up to 15 tries).
5. Container pages (`container: true`): run `prepare_js`, then press `Delete` to clear whatever body the page had (a guide that was split keeps its old text there otherwise), and check the title. A split guide with a top-level `00-index.md` isn't a container: its index is the page body and is pasted like any page.
6. **Verify after reload:** navigate to the page URL again and run `check_js` until it's `ok` (up to 10 tries). This proves Docmost saved it, not just displayed it.

`TOOL clip` fails, or the keystroke doesn't paste (some macOS setups ignore a synthetic Cmd+V) → use `paste_text_js` for the text, and keep uploading images with the recorded image method. Tell the user once that page text now passes through the conversation (slower, costs more). `paste_js` only if no image method works at all.

## 4. Calibrate (first sync, when `docmost.method` or `docmost.image_method` is null, or after a failure)

Prove the method on the **first content page that has a diagram** before syncing the rest:

1. Create or open that page (section 5, step 1) and write it as in section 3. For images, try `file-upload` first, then `clipboard-file`, then `paste-script`, and keep the first one where `images_uploaded` grows and a screenshot shows the diagram. Record it: `TOOL sync-record --repo REPO --method clipboard-markdown --image-method <method>` (`--method paste-markdown` if the text needed `paste_js`).
2. Also check with a screenshot that tables and Mermaid blocks render.
3. Nothing works for the text, or no image method works → stop. Show the user the screenshot and what failed. Don't improvise a method that might change URLs or lose content. Decide with the user.

**Recalibrate on failure:** when a page fails with a recorded method that worked before, Docmost's UI probably changed. Treat both methods as unknown, calibrate again on that page (which records the new ones), and retry it once. Still failing → stop the sync and report; don't push on through every page with a broken method.

### Diagram theme check (first sync, or when `docmost.diagram_theme` is not set)

Diagrams carry a light and a dark palette and switch by the viewer's color scheme. Check that they follow **Docmost's own theme toggle**:

1. Open a synced page that has a `.drawio.svg` diagram. Note which Docmost theme is active now.
2. Take a screenshot of the diagram. Switch Docmost's theme with its own toggle (find it with `find`/`read_page`, usually in the user or appearance menu), wait a second, and take another screenshot.
3. The diagram's background and shape colors changed with the page → `TOOL sync-record --repo REPO --diagram-theme adaptive`.
4. The page changed but the diagram didn't → images don't receive Docmost's toggle in this browser. Switch every diagram to the always-light palette: `TOOL svg-theme --repo REPO --mode light`, then `TOOL sync-record --repo REPO --diagram-theme light`, then run `TOOL sync-plan --repo REPO` again (every page with a diagram is now `changed`) and continue with the new plan. Tell the user the diagrams in `docs/` changed and need committing.
5. Switch Docmost back to the theme the user had.

Pages without draw.io diagrams (Mermaid only) skip this check, because Docmost renders Mermaid itself.

### List number check (first sync, or when `docmost.list_numbers` is not set)

Sequence stories are numbered lists whose numbers are the diagram's arrow numbers, so phase B's list may start at 5. Open a synced page with a sequence story and read its text (`get_page_text`). Find the first item under a phase heading other than `A.`:
- It shows its own number (e.g. `5.`) → `TOOL sync-record --repo REPO --list-numbers native`.
- Docmost restarted it at `1.` → `TOOL sync-record --repo REPO --list-numbers bold`, run `TOOL sync-plan --repo REPO` again (every page with a numbered list is now `changed`, and its prepared text uses bold numbers like `**5.**`), and continue with the new plan. The markdown files in GitLab keep their plain numbered lists.

## 5. Sync each page with `changed: true`, in plan order

1. **Find or create the page**
   - `existing_url` set → navigate to it. If it's gone (404), treat the page as new.
   - New → open the parent page (its URL from state, or `root_url` for `parent: null`). Create a child page with Docmost's "add subpage" control. Use `find`/`read_page` to locate it, since UI labels vary by version. Poll until the new page's editor shows (`prepare_js` returns `ok: true`).
2. **Write it** as in section 3, including the reload check.
3. **Record immediately**, so a failure halfway through doesn't lose the mapping:
   `TOOL sync-record --repo REPO --key <key> --url <current page URL> --content-hash <content_hash>`
4. On failure: record nothing for that page, recalibrate once (section 4), and skip the children of a page that failed to create.

## 6. Orphan pages

For `orphans` (a doc was split differently, merged back into one file, or an app left the repo), ask with **one** AskUserQuestion, listing each orphan's URL:
- **Archive**: rename the page to `[Archived] <its current title>` and move it under a page titled `Archive` directly under the root URL (create that page once if it's missing). Docmost's move is in the page menu; find it with `find`.
- **Delete**: deleting opens a confirmation dialog, which would block the extension. So open each page in the tab, point at Docmost's delete item in the page menu, and ask the user to click it and confirm. Wait for them to say it's done.

After either one, `TOOL sync-record --repo REPO --remove-key <key>`. If the user answers neither, leave the orphans; they're asked about again next time.

## 7. Report

Pages created, updated, unchanged, failed (with reason), archived and deleted, plus the Docmost URL of each app page, and the image method used. `sync-record` changed `docs/.docgen/state.json`, so remind the user to commit it. That's what lets the next sync, from any machine, update the same pages instead of creating duplicates.
