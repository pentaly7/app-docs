# Pipeline (shared by `generate` and `update`)

You are the orchestrator. `pipeline.py` decides everything: which app needs what, every script step between agents, the checks on each agent's output, resume after an interruption, and the final report. You launch the agents it asks for, ask the user its questions, and print its report. That keeps your context and your turns small, and it means no step can be skipped by mistake.

## Contents
1. Running it
2. Actions
3. Rules
4. What the script does (for maintainers)
5. Jobs and steps
6. Checks between agents
7. Workspaces
8. The workspace file

---

## 1. Running it

`PIPE` = `python3 <this skill's base directory>/../../shared/scripts/pipeline.py`. Run it from the folder the user is in, with no `cd`.

```
PIPE start --command <generate|update> [--drawio] [--fsm] [--max-apps N] [--unattended]
```

- `--drawio`: the arguments contain `drawio`, or the draw.io skill's instructions are already in this conversation (a "Base directory for this skill: …drawio…" header). Otherwise leave it out: diagrams are Mermaid.
- `--fsm`: the arguments contain `fsm`. It's remembered per app for later runs.
- `--max-apps N`: the arguments contain a number of apps (`max-apps 4`, `4 apps`). Without it, every app that needs work is started.
- `--unattended`: nobody can answer (a scheduled run). Every question takes its safe default.

`start` resumes an unfinished run of the same command instead of starting a new one. Every command prints one JSON **action**.

## 2. Actions

| `action` | What you do |
|---|---|
| `ask` | One AskUserQuestion call with every question in `questions` (`header`, `question`, `options` with `label` and `description`). Then `PIPE answer <id>=<value> …` with each chosen option's `value`. |
| `classify` | For each repo, decide which `candidates` are apps, by `rules`. Then `PIPE apps --json '{"<repo>": [{"path": "…", "id": "…", "kind": "…"}]}'`. |
| `agents` | Launch every task in `launch` with the Agent tool, all in **one message**: `subagent_type` as given (if the list shows plugin agents as `app-docs:<name>`, use that form), `description` and `prompt` exactly as given, in the background. Launch nothing else. |
| `wait` | Agents in `running` are still working. Wait for their completion notices. |
| `stop` | Tell the user the `say` text, and stop. |
| `done` | Print `say` exactly as it is, and stop. |

When an agent's completion notice arrives: `PIPE done --task <id>` (list every task that finished: `--task a --task b`). If an agent ended in an error rather than a summary: `PIPE done --failed <id> --error "<one line>"`. The result is the next action.

## 3. Rules

- Don't read application code, and don't open the agents' output files. Agents read code in their own context; the script checks their output.
- Don't run `docs_tool.py` yourself, and don't edit `docs/`, `state.json` or the run file. The script does all of that, in order.
- Don't pass one agent's summary to another, above all not to the goldfish reviewer: its value is that it starts fresh. You don't need to read the summaries closely either.
- Wait for every agent. Never stop or cancel one, and never launch a task twice. Taking a long time is normal.
- Lost track (the conversation was compacted, a command failed halfway)? `PIPE next` prints the current action without changing anything.
- Don't commit or push. Don't sync: every browser call in this conversation would re-send the whole run. The report ends with the line about syncing in a new conversation.

## 4. What the script does (for maintainers)

`start`, for every repo of the run (one repo, or a workspace: §7):
1. `docs_tool.py meta`; warnings for a missing `origin` remote, an unpushed HEAD, a repo on a Windows drive under WSL.
2. `docs/.docgen/.gitignore` with `.work/`, then `migrate` (no model: titles, subtitles, code links, Docmost page keys; it drops 2.x Dev Guide page keys).
3. Outside skills: humanizer-indonesia (always; the plugin's fallback rules when it's missing) and, with `--drawio`, the draw.io skill and CLI (Mermaid when either is missing; a stop when Graphviz is missing). `skill-pin` reports a changed skill.
4. Planning (§5): new apps to classify, `drift`, `upgrade-plan`, and the jobs of each app.
5. Questions, asked once for the whole run: uncommitted changes, plugin upgrades (with the token estimate), splitting when a repo passes 10 apps, and apps left mid-run by 2.x. Unattended defaults: continue, not now, not now, stop.

Then `next` advances every app as far as script steps go, queues agent tasks, and launches up to **3 at a time** across all repos, in run order. More at once doesn't use fewer tokens; it only reaches a usage limit sooner, with more work cut off when it does.

Recovery: a task still `running` when `start` runs again (the session ended, a usage limit hit) is checked on disk. A flow agent whose fragment `state.json` exists finished; flows still missing get a new brief with only those flows. A goldfish whose findings file is complete finished. Other agents are launched again and pick up their own partial work. A failed app resumes at the step that failed.

## 5. Jobs and steps

Each app gets a queue of jobs, stored in `state.json → apps.<id>` (`job`, `step`, `jobs`, `flows_todo`, `flows_done`, `job_started`), so a cut-off run resumes at the same step. `stage` is `pending`, `working`, `failed` or `done`.

| Job | When | Steps |
|---|---|---|
| `fresh` | new app | app (`app`) → flows (`flow`) → assemble → review → fix → humanize → finish |
| `update` | drift, or FSM newly enabled | app (`update`) → flows (stale or new important flows) → assemble → review → fix → humanize → finish |
| `regenerate` | template upgrade with no step path, split forced, or a 2.x app restarted | as update, with "Template changed: yes" and every important flow |
| `extend` | accepted upgrade | app (`extend`) → assemble → review → fix → humanize → finish |
| `facts` | accepted upgrade, or template 3 with drift | app (`facts`) → finish |
| `redraw` | accepted upgrade, same diagram mode | app and flows (`redraw`) at once → assemble → humanize → finish |
| `restory` | accepted upgrade | flows (`story`) → assemble → humanize → finish |
| `rehumanize` | accepted upgrade | humanize (whole User Guide) → finish |

Template jobs come first, then update, redraw, restory, rehumanize. After every app of a repo finishes an accepted upgrade, `state.json`'s versions are set to the plugin's.

**Scope.** Before each job the script hashes every section's text. Review and humanizer scope is the sections whose text the job changed (the whole guide for `fresh`, `regenerate` and `rehumanize`). An empty scope skips review, fix and humanizer.

**Reading lists.** The script puts each agent's reading list in its prompt, per mode (`reading_list` in pipeline.py): story and redraw agents don't get the writing templates, Mermaid runs don't get the draw.io spec rules, FSM rules only with FSM on.

## 6. Checks between agents

- **Keep blocks:** `keep-snapshot` before the first agent touches an app in a run; `keep-restore` after every agent that writes the guides, and after assemble. Restored blocks are reported: an agent that drops them needs its prompt checked.
- **Agent output:** app-documenter must leave a readable app state with flows and both guides (`facts`: template 4; `extend`: the named sections). A flow is done only when its fragment `state.json` exists. The goldfish must leave a findings file. Anything missing fails the app at that step, or, for flows, is reported and left as a placeholder (the validator flags `flow-not-assembled`).
- **Assemble:** fragments into the guides, facts and app state; `render --refresh-owners` once per run (the owners snapshot), then a facts snapshot (`draft`).
- **Fix:** `render`, then `facts-diff` against the draft. Fixes may change facts, so this is reported, not blocked ("Fix changed facts").
- **Humanizer:** `humanize-plan` (nothing to polish → no agent), a facts snapshot, the agent, `render`, then `facts-diff --only op --strict`. Any change gets one more humanizer pass with the `changes` list ("put back exactly these facts"); still changed → validator failure `humanizer-fact-changed`. Never a loop.
- **Finish:** `svg-theme` (diagrams in `docs/` always adaptive), `stamp`, `validate`. Validator failures don't block; they go in the report with the goldfish counts, fact changes, guide mismatches and restored keep blocks.
- **Report:** one block per app, failures first, then `usage-spend` since the run started: output, cache reads, cache writes and uncached input per model, and the main session's model.

## 7. Workspaces

Run from a folder that isn't inside a git repo, and every git repo one or two folders below it is part of the run (`parent/svc-a/`, `parent/group/svc-b/`). Inside a repo the search stops, so its nested clones and submodules aren't separate repos. Dependency folders (`vendor/`, `node_modules/`, …) and hidden folders are skipped. Run from inside a repo, it's a single-repo run, even when that repo is part of a workspace.

Repos run **callees first**: a service another one calls is documented before it, so its doc paths exist when the caller's agent writes links. The calls are guessed from config files (other repos' names in base URLs, env keys like `WALLET_SVC_URL`, compose service names). A wrong guess only costs some links on the first pass. Agents get every other app as a link target: a relative path inside the repo, a GitLab link (`<repo>/-/blob/HEAD/<path>`) for another repo (conventions §12).

`--max-apps N` starts at most N apps that need work, in run order; apps already in progress count first. The rest are listed as not started.

## 8. The workspace file

`<parent>/.app-docs-workspace.json`, not committed anywhere (the parent folder isn't a repo):

```json
{
  "repos": [{"path": "db-service"}, {"path": "group/wallet"}, {"path": "shop"}],
  "calls": {"shop": ["wallet"], "wallet": ["db-service"], "db-service": []},
  "calls_source": "guessed",
  "docmost": {"root_url": "…", "method": "clipboard-markdown", "image_method": "file-upload", "diagram_theme": "adaptive", "list_numbers": "native", "image_reuse": "ok"}
}
```

- `repos`: in run order, rewritten on every run.
- `calls`: guessed again on every run. To fix a wrong guess, edit it and set `"calls_source": "manual"`; the script then keeps it.
- `docmost`: the sync calibration, shared by every repo synced to that Docmost (sync skill). Each repo's `state.json` keeps its own copy and its own page URLs.
- The run in progress is kept beside it in `.app-docs-run.json`; for a single repo, in `docs/.docgen/.work/run.json`.
