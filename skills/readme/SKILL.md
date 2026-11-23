---
name: readme
description: Rewrite README.md files from the app-docs Dev Guides, by script, with no model. Each app's folder gets a self-contained README (what it is, tech stack, quick start, configuration, structure diagram, flows, doc links, owners, and the commit the docs were generated from), and a monorepo root gets an index of all apps. Needs Dev Guides from /app-docs:generate first.
disable-model-invocation: true
---

# Rewrite READMEs from the Dev Guides

Arguments: `$ARGUMENTS`

Each README is **rewritten in full** from its app's Dev Guide. Nothing outside the Dev Guide goes in, and stale statements in the old README are corrected. It's English only, with no goldfish review.

`TOOL` = `python3 <this skill's base directory>/../../shared/scripts/docs_tool.py`. `SHARED` = `<this skill's base directory>/../../shared`. `REPO` = `git rev-parse --show-toplevel`.

## Steps

1. **Plan.** Run `TOOL migrate --repo REPO`, then `TOOL readme-plan --repo REPO`.
   - Error "no state.json", or `missing_dev_guide` isn't empty → **stop**. Tell the user which apps have no finished Dev Guide and to run `/app-docs:generate` first. Write nothing.

2. **Confirm the commit.** The README is copied from the Dev Guide, so it's only as current as the Dev Guide. If `docs_behind_head` isn't empty, or `dirty` is true, ask the user before writing anything (AskUserQuestion; in plain text if that tool isn't available). Show, per app: the commit of the Dev Guide's oldest section and its date, the current `head_sha`, and `commits_since_verified`. Options:
   - **Continue**: write the READMEs from the Dev Guides as they are. Each README's footer shows that commit.
   - **Stop**: the user runs `/app-docs:update` first, then `/app-docs:readme` again.

   If no one is there to answer, stop rather than guess.

3. **Write.** `TOOL readme --repo REPO`. It rewrites every app README, and the root index in a monorepo, from the Dev Guide sections and the facts file (`shared/references/readme-template.md`). No model is involved, so a README can only say what the Dev Guide says.

4. **Report.** One line per README written; under `old_readme_claims_corrected`, the old README claims the Dev Guide had already marked as contradictions (these are now gone from the README); the owners source; and which READMEs have no Docmost link yet (run `/app-docs:sync`, then `/app-docs:readme` again to add it). Nothing is committed. The user reviews the diff, especially the replaced READMEs.

## Shell commands

If you run a shell command yourself, use `command <tool> … < /dev/null` with explicit paths, so the user's shell aliases can't make it hang.
