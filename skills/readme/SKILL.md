---
name: readme
description: Rewrite README.md files from the app-docs Dev Guides. Each app's folder gets a self-contained README (what it is, tech stack, quick start, configuration, structure diagram, flows, doc links, owners, last-verified commit), and a monorepo root gets an index of all apps. Needs Dev Guides from /app-docs:generate first.
disable-model-invocation: true
---

# Rewrite READMEs from the Dev Guides

Arguments: `$ARGUMENTS`

Each README is **rewritten in full** from its app's Dev Guide. Nothing outside the Dev Guide goes in, and stale statements in the old README are corrected. It's English only, with no goldfish review.

`TOOL` = `python3 <this skill's base directory>/../../shared/scripts/docs_tool.py`. `SHARED` = `<this skill's base directory>/../../shared`. `REPO` = `git rev-parse --show-toplevel`.

## Steps

1. **Plan.** Run `TOOL migrate --repo REPO`, then `TOOL readme-plan --repo REPO`.
   - Error "no state.json", or `missing_dev_guide` isn't empty → **stop**. Tell the user which apps have no finished Dev Guide and to run `/app-docs:generate` first. Write nothing.

2. **Confirm the commit.** The README is copied from the Dev Guide, so it's only as current as the Dev Guide. If `docs_behind_head` isn't empty, or `dirty` is true, ask the user before writing anything (AskUserQuestion; in plain text if that tool isn't available). Show, per app: the Dev Guide's verified commit and date, the current `head_sha`, and `commits_since_verified`. Options:
   - **Continue**: write the READMEs from the Dev Guides as they are. Each README's footer shows the verified commit.
   - **Stop**: the user runs `/app-docs:update` first, then `/app-docs:readme` again.

   If no one is there to answer, stop rather than guess.

3. **Write the app READMEs.** One `readme-writer` agent per app, up to 3 at a time, waiting for every agent to finish (never cancel one). Prompt:
   ```
   Repo root: <REPO>
   Shared folder: <SHARED>
   Write: app README
   Plan entry: <this app's entry from readme-plan, as JSON>
   ```
   For a single-app repo (the app's root is the repo root), this README is the root README and step 4 is skipped.

4. **Write the root index** (monorepo only: `root_index` isn't null), after the app READMEs exist, with one `readme-writer`:
   ```
   Repo root: <REPO>
   Shared folder: <SHARED>
   Write: root-index README at README.md
   Owners: <root_index.owners as JSON>
   Apps: <every app entry from readme-plan, as JSON>
   ```

5. **Report.** One line per README written, the corrected claims each agent listed, the owners source, and which READMEs have no Docmost link yet (run `/app-docs:sync`, then `/app-docs:readme` again to add it). Nothing is committed. The user reviews the diff, especially the replaced READMEs.

## Shell commands

If you run a shell command yourself, use `command <tool> … < /dev/null` with explicit paths, so the user's shell aliases can't make it hang.
