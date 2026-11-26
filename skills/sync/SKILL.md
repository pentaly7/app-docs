---
name: sync
description: One-way sync of one repo's User Guides in /docs to Docmost (community edition, no API) through the user's logged-in Chrome. Each app's page is its User Guide; split guides hang their pages under it. The Dev Guide stays in GitLab. Pages are created the first time and updated in place later, so URLs stay stable. Run in a repo to sync it, or in a workspace folder to sync the next repo that needs it (callees first); each repo gets its own new conversation. Pass the Docmost space or parent-page URL on the first run; it's saved for later runs.
argument-hint: "[docmost-url]"
disable-model-invocation: true
model: sonnet
---

# Sync User Guides to Docmost

Arguments: `$ARGUMENTS`

Docmost community edition has no API keys or MCP here, so sync drives the Docmost web UI in the user's Chrome, which is already logged in. Sync is **one-way**: the markdown in GitLab is the source of truth. Only User Guides are synced; developers read the Dev Guide in GitLab.

**One repo per conversation.** Every browser call re-sends the whole conversation, so a second repo in the same conversation would cost far more than the first. If this conversation already holds a generate, an update or another repo's sync, say so and ask the user to start a new one; go on only if they want to.

`PIPE` = `python3 <this skill's base directory>/../../shared/scripts/pipeline.py`. `TOOL` = `python3 <this skill's base directory>/../../shared/scripts/docs_tool.py`. `REPO` = the repo synced in this conversation.

## 1. Which repo, and what changes

1. `PIPE targets` from the folder the user is in. It lists the repos (callees first in a workspace) and, per app, the pages to create or update, links waiting for their target, orphans, and whether Docmost is calibrated. No page text: keep it that way.
2. `REPO` is `next`. In a workspace, say which repo this conversation syncs, and which ones follow (`after`).
   - `next` is null → "Docmost is up to date", and stop.
   - A repo with `skip` → mention it. With `error` (two files map to the same page) → tell the user to fix that repo's docs first (validate reports `anchor-duplicate`): syncing would overwrite one page with the other's text. `not_done` apps aren't synced; mention them.
3. Root URL: a URL in the arguments → `TOOL sync-record --repo REPO --root-url <url>` (in a workspace it's saved for every repo). No URL and `root_url` is null → ask for the Docmost space or parent-page URL and stop until they answer.
4. `TOOL sync-plan --repo REPO`. It lists every page in parent-before-child order, with:
   - `key`, `parent` (a key, or null for directly under the root URL), `title`, `existing_url`, `changed`, `content_hash`
   - `container: true`: a page with no body of its own (a split guide without a top `00-index.md`)
   - `prepared_file`: the page body as markdown, diagrams replaced by `[[diagram:<name>]]` placeholders, links to other apps' User Guides already turned into their Docmost URLs (or into plain text, listed in `links_pending`, until those pages exist)
   - `prepare_js` (sets the title and selects the whole body), `check_js` (reports what the body holds now), `images_js` (lists the image addresses in the page)
   - `images[]`: diagrams to **upload** on this page, each with `name`, `path`, `place_js` (selects and deletes its placeholder, leaving the cursor there) and `image_js` (last-resort fallback)
   - `images_linked`: diagrams already uploaded on another page; the prepared text links to them
   - `paste_text_js` (title and body by script, text only) and `paste_js` (the same with diagrams as base64): fallbacks
   - `method`, `image_method`, `diagram_theme`, `list_numbers`, `image_reuse`: the calibration so far (in a workspace, shared by every repo)
   - `orphans`: pages synced before whose doc no longer exists
5. Say how many pages will be created or updated, and that Chrome must stay open and logged in to Docmost. Titles: use each page's `title` exactly.
6. **First sync only** (no `method` yet): tell the user once that each sync replaces whole page bodies. Edits made in Docmost are overwritten, and inline comments (attached to text) are lost or detached. Notes belong in their own Docmost pages, or in a merge request on the markdown. `<!-- app-docs:keep -->` text is synced like any other text.

## 2. Open Chrome

Load the `chrome-browser` skill with the Skill tool if it's listed. Load the browser tools in **one** ToolSearch call:
`select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__find,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__get_page_text,mcp__claude-in-chrome__file_upload,mcp__claude-in-chrome__tabs_close_mcp`

No such tools, or they can't reach Chrome → say that sync needs Claude Code running locally with Chrome and the Claude in Chrome extension connected (`claude --chrome`, or the desktop app), and stop.

Call `tabs_context_mcp`, open a **new** tab, and navigate to the root URL. A login page → ask the user to log in in that tab and say when done.

**Always name the tab.** Pass its `tabId` on every call. After every `navigate` or reload, call `tabs_context_mcp` again and use the `tabId` it reports. "Couldn't determine which page this action targets" comes from calls made right after a page change, and a refused call in the middle of placing an image leaves the editor half-done. When a call is refused anyway, run `check_js` first and repair from the page's real state. Avoid anything that opens a browser dialog (delete, "leave page?"): dialogs block the extension.

## 3. Write one page

Page text goes through the **OS clipboard**, not through this conversation. `TOOL clip <prepared_file>` copies it, and a real keystroke pastes it, so Docmost's own paste handler converts the markdown, exactly as when a person pastes.

1. Run its `prepare_js` with `javascript_tool`. `ok: false` → the editor isn't ready; wait 2 seconds and try once more.
2. `TOOL clip <prepared_file>`, then press `cmd+v` (macOS) or `ctrl+v` (others) with `computer` → `key`.
3. **Poll, don't sleep:** run `check_js` every 2 seconds, up to 15 times, until all three hold: `literal_markdown` is false, `headings` reached the plan's count, and `placeholders` equals the page's number of images. Timeout → the page failed.
4. For each image, in order: run its `place_js`, then insert the file with the recorded `image_method`:
   - `file-upload`: open Docmost's image insert at the cursor (type `/image` and choose the upload item; find it with `find`, since labels vary by version), then `file_upload` with the image `path` on the file input it opens.
   - `clipboard-file`: `TOOL clip <path> --file-ref`, then paste with the keystroke.
   - `paste-script`: run its `image_js` (the image passes through the conversation: last resort).
   Poll `check_js` until `images_uploaded` grew by one (up to 15 tries).
5. Container pages: run `prepare_js`, press `Delete` to clear whatever body the page had, and check the title.
6. **Verify after reload:** navigate to the page URL again and run `check_js` until it's `ok` (up to 10 tries). This proves Docmost saved the page, not just displayed it.
7. **Record the uploads**, if `images` wasn't empty: run `images_js` and pass its output, as is, to `TOOL sync-record --repo REPO --key <key> --image-urls '<output>'`. Then run `TOOL sync-plan --repo REPO` again before the next page, so later pages link to these uploads.

If `TOOL clip` fails, or the keystroke doesn't paste (some macOS setups ignore a synthetic Cmd+V), use `paste_text_js` for the text and keep uploading images by file. Tell the user, since page text then passes through the conversation. Use `paste_js` only if no image method works.

## 4. Calibrate (first sync, or after a failure)

With no `method` yet, calibrate on the **first page that has a diagram**, before the rest:
1. Write it as in §3. For images, try `clipboard-file`, then `file-upload` (Docmost's image item may open the OS file picker, which the extension can't operate), then `paste-script`. Keep the first where `images_uploaded` grows and a screenshot shows the diagram. Record: `TOOL sync-record --repo REPO --method clipboard-markdown --image-method <method>` (`--method paste-markdown` if the text needed `paste_text_js`). In a workspace this is saved for every repo.
2. Check with a screenshot that tables and Mermaid blocks render.
3. **Image reuse:** on the first page with `images_linked` above 0, screenshot after the reload check. Linked diagrams show → `TOOL sync-record --repo REPO --image-reuse ok`. Broken images → `--image-reuse off`, re-plan (those pages upload their own copies) and redo that page.
4. Nothing works for the text, or no image method works → stop, show the user what you tried and the screenshot, and decide with them. Don't improvise a method that might change URLs or lose content.

**Recalibrate on failure.** A page fails with a method that worked before → Docmost's UI probably changed. Calibrate again on that page and retry it once. Still failing → stop and tell the user what failed; don't push through every page with a broken method.

### Checks, once per Docmost (`diagram_theme` or `list_numbers` still null)

- **Diagram theme:** on a page with a `.drawio.svg` diagram, note Docmost's theme and screenshot the diagram. Switch Docmost's theme with its own toggle (`find`/`read_page`, usually in the user or appearance menu), wait a second, and screenshot again.
  - The diagram followed → `TOOL sync-record --repo REPO --diagram-theme adaptive`.
  - It didn't → `--diagram-theme light`. Re-plan: every page with a diagram is now `changed`, and sync uploads always-light copies; the files in `docs/` stay as they are. Continue with the new plan.

  Switch the theme back afterwards. Pages with only Mermaid skip this check.
- **List numbers:** on a page with a sequence story, read it (`get_page_text`) and find the first item under a phase heading other than `A.`.
  - It shows its own number (`5.`) → `--list-numbers native`.
  - Docmost restarted it at `1.` → `--list-numbers bold`. Re-plan (pages with numbered lists are now `changed`) and continue.

## 5. Each page with `changed: true`, in plan order

1. **Find or create it.** `existing_url` set → navigate to it (404 → treat as new). New → open the parent page (the parent's `existing_url` in the plan, or the root URL for `parent: null`) and create a child page with Docmost's "add subpage" control (`find`/`read_page`: labels vary by version). Poll until the editor shows (`prepare_js` returns `ok: true`).
2. **Write it** as in §3, reload check included.
3. **Record right away**, so a failure halfway doesn't lose the mapping: `TOOL sync-record --repo REPO --key <key> --url <current page URL> --content-hash <content_hash>`.
4. On failure: record nothing for that page, recalibrate once (§4), and skip the children of a page that failed to create.

## 6. Orphans

Ask with **one** AskUserQuestion, listing each orphan's URL:
- **Archive**: rename the page to `[Archived] <its current title>` and move it under a page titled `Archive` directly under the root URL (create it once if it's missing). Docmost's move is in the page menu; find it with `find`.
- **Delete**: deleting opens a confirmation dialog, which would block the extension. Open each page, point at Docmost's delete item in the page menu, and ask the user to click it and confirm. Wait until they say it's done.

After either one, run `TOOL sync-record --repo REPO --remove-key <key>`. If they pick neither, leave the pages; they're asked about again next time.

## 7. Report, and the next repo

Close the tab. Report pages created, updated, unchanged, failed (with reason), archived and deleted; links left as plain text (`links_pending`); the Docmost URL of each app page; the image method.

`sync-record` changed `REPO`'s `docs/.docgen/state.json`, so remind the user to commit it. That's what lets the next sync, from any machine, update the same pages instead of creating duplicates.

Then run `PIPE targets` again and tell the user what's next:
- Another repo has work (`next`) → "Start a **new conversation** and run `/app-docs:sync` again (from the parent folder, or inside `<next repo>`)". List the repos still to sync.
- Links in this repo still wait for a repo that hasn't been synced yet → they become links when this repo is synced again after that one. `targets` will list this repo again at that point.
- Nothing left → "Docmost is up to date".
