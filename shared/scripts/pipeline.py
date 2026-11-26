#!/usr/bin/env python3
"""app-docs pipeline: the sequencing of a generate or update run, for one repo or a workspace of repos.

The orchestrator (a model) only launches agents, asks the user and prints the report. Everything else
happens here: which app needs what, every non-model step between agents, checking each agent's output on
disk, and resuming after an interruption. Each command prints one JSON action:

  start    begin or resume a run in the current folder (a repo, or a parent folder of repos)
  answer   record the user's answers to an "ask" action
  apps     record which detected candidates are apps (answer to a "classify" action)
  done     report finished (or failed) agent tasks
  next     the next action without reporting anything (after a restart, or when unsure)

Actions: ask, classify, agents (launch these tasks), wait (agents still running), stop, done (with the report).
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import docs_tool as dt  # noqa: E402

SHARED = HERE.parent
TOOL = HERE / "docs_tool.py"
PARALLEL = 3          # agents at once: more only reaches a usage limit sooner, with more work cut off when it does
RUN_FILE = ".app-docs-run.json"
WORK = Path(dt.DOCS_DIR) / ".docgen" / ".work"

# Steps of each job. "app" and "flows" (and "redraw", both at once) are agent steps; "review", "fix" and
# "humanize" have an agent part; "assemble" and "finish" are script only.
STEPS = {
    "fresh": ["app", "flows", "assemble", "review", "fix", "humanize", "finish"],
    "update": ["app", "flows", "assemble", "review", "fix", "humanize", "finish"],
    "regenerate": ["app", "flows", "assemble", "review", "fix", "humanize", "finish"],
    "extend": ["app", "assemble", "review", "fix", "humanize", "finish"],
    "facts": ["app", "finish"],
    "redraw": ["redraw", "assemble", "humanize", "finish"],
    "restory": ["flows", "assemble", "humanize", "finish"],
    "rehumanize": ["humanize", "finish"],
}
APP_MODE = {"fresh": "app", "update": "update", "regenerate": "update", "extend": "extend", "facts": "facts", "redraw": "redraw"}
FLOW_MODE = {"fresh": "flow", "update": "flow", "regenerate": "flow", "redraw": "redraw", "restory": "story"}
WHOLE_GUIDE = {"fresh", "regenerate", "rehumanize"}   # review and humanizer cover every section


class Stop(Exception):
    """A condition the run can't get past without the user (printed as a stop action)."""


# ---------------------------------------------------------------- small helpers

def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tool(repo, *args, codes=(0, 1)):
    """Run one docs_tool.py command and return its JSON. Exit 1 is a finding, not an error."""
    proc = subprocess.run([sys.executable, str(TOOL), *args, "--repo", str(repo)], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, cwd=str(repo))
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        out = {"error": (proc.stderr or proc.stdout).strip()[-400:]}
    if proc.returncode not in codes:
        raise RuntimeError("docs_tool %s: %s" % (args[0], out.get("error") or out))
    out["_code"] = proc.returncode
    return out


def state_path(repo):
    return Path(repo) / dt.DOCS_DIR / ".docgen" / "state.json"


def load_state(repo):
    path = state_path(repo)
    return dt.load_json(path) if path.exists() else None


def app_file(repo, app_id):
    return Path(repo) / dt.DOCS_DIR / ".docgen" / "apps" / ("%s.json" % app_id)


def rel(repo, path):
    return Path(path).relative_to(repo).as_posix()


def in_work(repo, *parts):
    path = Path(repo) / WORK / Path(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------- where the run is

def discover(folder):
    """("repo", [root]) inside a git repo, else ("workspace", [repos]): git repos one or two folders below,
    not descending into a repo once found (its nested clones and submodules belong to it), and skipping
    dependency folders such as vendor/ and node_modules/."""
    folder = Path(folder).resolve()
    top = subprocess.run(["git", "-C", str(folder), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL)
    if top.returncode == 0:
        return "repo", [Path(top.stdout.strip()).resolve()]

    def candidates(parent):
        try:
            children = sorted(p for p in parent.iterdir() if p.is_dir())
        except OSError:
            return []
        return [p for p in children if not p.name.startswith(".") and p.name not in dt.PRUNE_DIRS]

    repos = []
    for child in candidates(folder):
        if (child / ".git").exists():
            repos.append(child)
            continue
        repos += [grand for grand in candidates(child) if (grand / ".git").exists()]
    if not repos:
        raise Stop("Not inside a git repository, and no git repositories one or two folders below %s." % folder)
    return "workspace", repos


def run_file(root, kind):
    return Path(root) / RUN_FILE if kind == "workspace" else Path(root) / WORK / "run.json"


def load_run(root):
    kind, repos = discover(root)
    root = Path(root).resolve() if kind == "workspace" else repos[0]
    path = run_file(root, kind)
    if not path.exists():
        raise Stop("No run in progress here. Start one with /app-docs:generate or /app-docs:update.")
    return path, dt.load_json(path)


def save_run(path, run):
    dt.save_json(path, run)


# ---------------------------------------------------------------- calls between repos (workspace order)

CONFIG_SUFFIXES = (".env", ".env.example", ".yaml", ".yml", ".toml", ".properties", ".json", ".conf", ".ini")


def _config_text(repo, limit=400):
    """Config-like files of a repo (not code): where one service names the services it calls."""
    chunks, count = [], 0
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in dt.PRUNE_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.endswith(CONFIG_SUFFIXES) or name.startswith((".env", "docker-compose", "compose")):
                if name in ("package.json", "package-lock.json", "composer.json", "composer.lock", "tsconfig.json"):
                    continue
                chunks.append(dt._read(Path(dirpath) / name, 50_000).lower())
                count += 1
                if count >= limit:
                    return "\n".join(chunks)
    return "\n".join(chunks)


def _reference_patterns(name):
    """Ways a config file points at another service, and not merely shares a word with it: a URL host
    (`http://wallet:8080`) or an address key (`WALLET_URL`, `DB_SERVICE_HOST`). A database or a path
    named like the service (`postgres://…/wallet`) doesn't count."""
    base = dt._kebab(name)
    forms = sorted({base, base.replace("-", "_"), base.replace("-", "")}, key=len, reverse=True)
    names = "|".join(re.escape(f) for f in forms)
    host = r"://(?:[^/\s@]*@)?(?:%s)(?=[:/.\"'\s]|$)" % names
    key = r"(?<![a-z0-9])(?:%s)[_-]?(?:svc[_-]|service[_-])?(?:url|uri|host|addr|address|endpoint|base[_-]?url|grpc[_-]addr|api[_-]url)(?![a-z0-9])" % names
    return re.compile("%s|%s" % (host, key), re.M)


def guess_calls(repos):
    """{repo name: [repo names it seems to call]}, from other repos' names in its config as URL hosts or
    address keys. A guess: it only orders the run, so callees are documented before their callers."""
    names = {Path(r).name: Path(r) for r in repos}
    patterns = {name: _reference_patterns(name) for name in names}
    calls = {}
    for name, path in names.items():
        text = _config_text(path)
        calls[name] = sorted(other for other in names if other != name and patterns[other].search(text))
    return calls


def callee_order(names, calls):
    """Callees before callers; a cycle is broken by name order, so the result is stable."""
    order, visiting = [], set()

    def visit(name):
        if name in order or name in visiting:
            return
        visiting.add(name)
        for callee in sorted(calls.get(name, [])):
            visit(callee)
        visiting.discard(name)
        order.append(name)
    for name in sorted(names):
        visit(name)
    return order


def workspace_file(root):
    return Path(root) / dt.WORKSPACE_FILE


def sync_workspace(root, repos):
    """Create or refresh the workspace file: repos in callee order. Calls are guessed again on every run
    unless someone set "calls_source": "manual" after editing them."""
    path = workspace_file(root)
    workspace = dt.load_json(path) if path.exists() else {}
    if workspace.get("calls_source") != "manual":
        workspace["calls"] = guess_calls(repos)
        workspace["calls_source"] = "guessed"
    by_name = {Path(r).name: Path(r) for r in repos}
    order = callee_order(by_name, workspace.get("calls", {}))
    workspace["repos"] = [{"path": by_name[n].relative_to(root).as_posix()} for n in order]
    workspace.setdefault("docmost", {})
    dt.save_json(path, workspace)
    return [by_name[n] for n in order], workspace


# ---------------------------------------------------------------- environment

def find_skill(repo, name):
    home = Path.home()
    patterns = [home / ".claude" / "skills", Path(repo) / ".claude" / "skills", home / ".agents" / "skills"]
    for base in patterns:
        for folder in sorted(base.glob(name)) if base.is_dir() else []:
            if (folder / "SKILL.md").is_file():
                return folder
    plugins = home / ".claude" / "plugins"
    if plugins.is_dir():
        for skill_md in sorted(plugins.glob("**/skills/%s/SKILL.md" % name)):
            return skill_md.parent
    return None


def environment(repos, drawio_asked):
    """Diagram mode and outside skills, once per run."""
    env = {"diagram_mode": "mermaid", "drawio_skill": None, "humanizer_skill": None, "notes": []}
    humanizer = find_skill(repos[0], "humanizer-indonesia")
    env["humanizer_skill"] = str(humanizer) if humanizer else None
    if not humanizer:
        env["notes"].append("humanizer-indonesia not installed: using the plugin's fallback rules. Install: "
                            "`git clone https://github.com/adhiprib/humanizer-indonesia ~/.claude/skills/humanizer-indonesia`")
    if drawio_asked:
        skill = find_skill(repos[0], "*drawio*")
        cli = dt._drawio_bin()
        if not skill or not cli:
            env["notes"].append("draw.io %s not found: using Mermaid" % ("skill" if not skill else "CLI"))
        else:
            dot = subprocess.run(["dot", "-V"], capture_output=True, text=True, stdin=subprocess.DEVNULL) if shutil.which("dot") else None
            if dot is None or dot.returncode != 0:
                raise Stop("draw.io mode needs Graphviz for the diagram layout. Install it and run again: "
                           "`brew install graphviz` (macOS), `sudo apt install graphviz` (Debian/Ubuntu), `winget install graphviz` (Windows).")
            env.update(diagram_mode="drawio", drawio_skill=str(skill))
    return env


def preflight(repo, run):
    """The free, mechanical part of a run for one repo: meta, .gitignore, migrate, skill pins."""
    info = {"name": Path(repo).name, "notes": []}
    meta = tool(repo, "meta")
    meta.pop("_code", None)
    info["meta"] = meta
    if meta.get("windows_drive"):
        info["notes"].append("on a Windows drive under WSL: git and layout run several times slower, and line-ending noise can show every file as changed. Clone it into the Linux home folder.")
    if meta.get("web_url") is None:
        info["notes"].append("no `origin` remote: code references stay plain text, without GitLab links")
    elif meta.get("head_pushed") is False:
        info["notes"].append("HEAD isn't pushed yet: the Dev Guide's code links will 404 until you push it")
    if state_path(repo).exists():
        ensure_ignore(repo)
        migrated = tool(repo, "migrate")
        counts = {k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in migrated.items()
                  if k in ("titles", "subtitles", "links", "page_keys", "dev_pages_dropped") and v}
        if counts:
            info["notes"].append("migrate: %s" % ", ".join("%s %s" % (v, k) for k, v in counts.items()))
        if (Path(repo) / dt.DOCS_DIR / ".docgen" / "bin").exists() or (Path(repo) / dt.DOCS_DIR / ".docgen" / "gitlab-ci.app-docs.yml").exists():
            info["notes"].append("docs/.docgen/bin/ and docs/.docgen/gitlab-ci.app-docs.yml (the removed CI check) can be deleted, with their `include:` line")
        for name, key in (("humanizer-indonesia", "humanizer_skill"), ("drawio", "drawio_skill")):
            if run["env"].get(key):
                pin = tool(repo, "skill-pin", "--name", name, "--dir", run["env"][key])
                if pin.get("changed"):
                    info["notes"].append("%s changed since the last run (`%s` → `%s`): sections written in this run may read or look different from older ones. Nothing else is redone."
                                         % (name, (pin.get("previous") or {}).get("commit"), pin["pin"].get("commit")))
    return info


# ---------------------------------------------------------------- planning: which app needs what

def _job(name, **extra):
    return dict(extra, name=name)


def plan_repo(repo, run):
    """Questions to ask, candidates to classify, and the jobs of every app in one repo (after answers)."""
    key = str(repo)
    info = run["repos"][key]
    answers = run["answers"]
    state = load_state(repo)
    if state is None:
        if run["command"] == "update":
            info["notes"].append("not documented yet: run /app-docs:generate")
            info["skip"] = True
            return
        if key not in run.get("classified", {}):
            info["classify"] = dt.detect_apps(repo)
            return
        state = {"template_version": dt.TEMPLATE_VERSION, "humanizer_version": dt.HUMANIZER_VERSION,
                 "diagram_version": dt.DIAGRAM_VERSION, "story_version": dt.STORY_VERSION, "apps": {}, "docmost": {}}
    drift = tool(repo, "drift") if state.get("apps") else {"apps": {}, "missing_app_state": [], "new_app_candidates": []}
    plan = tool(repo, "upgrade-plan") if state.get("apps") else {"pending": []}
    info["upgrade"] = [p for p in plan.get("pending", [])]
    upgrade_now = answers.get("upgrade") == "now"

    # new apps and apps whose state file is gone
    candidates = drift.get("new_app_candidates", [])
    if candidates and run["command"] == "generate" and key not in run.get("classified", {}):
        info["classify"] = candidates
        return
    if candidates and run["command"] == "update":
        info["notes"].append("new apps not documented: %s → run /app-docs:generate" % ", ".join(c["path"] for c in candidates))
    for app_id in drift.get("missing_app_state", []):
        if state["apps"][app_id].get("stage") != "done":
            continue                               # never documented, or its first job is still writing it
        if run["command"] == "generate":
            state["apps"][app_id].update(stage="pending")
            for k in ("job", "step", "jobs"):
                state["apps"][app_id].pop(k, None)
        else:
            info["notes"].append("%s has no app state: run /app-docs:generate" % app_id)
    for item in run.get("classified", {}).get(key, []):
        state["apps"].setdefault(item["id"], {"root": item["path"], "kind": item.get("kind"), "stage": "pending",
                                              "fsm": bool(run["options"].get("fsm"))})
    apps_now = len(state["apps"])
    if apps_now > 10 and not state.get("split_all"):
        state["split_all"] = True
        if any(a.get("stage") == "done" for a in state["apps"].values()):
            info["split_flip"] = True
    if run["options"].get("fsm"):
        for app in state["apps"].values():
            if not app.get("fsm"):
                app["fsm"] = True
                app["fsm_new"] = app.get("stage") == "done"

    legacy = [a for a, v in state["apps"].items() if v.get("stage") not in ("done", "pending") and "job" not in v]
    if legacy:
        info["legacy"] = legacy
        if answers.get("legacy") != "start-fresh":
            dt.save_json(state_path(repo), state)
            return
    for app_id, app in sorted(state["apps"].items()):
        if app_id in legacy:
            app.update(stage="pending" if not app_file(repo, app_id).exists() else "done", jobs=[], legacy=True)
            shutil.rmtree(Path(repo) / WORK / "fragments" / app_id, ignore_errors=True)
        if app.get("job"):
            continue                                   # a 3.0 run was cut off: resume where it stopped
        if run["report"].get(key, {}).get(app_id, {}).get("status") == "done":
            continue                                   # finished earlier in this run
        jobs = []
        if app.get("stage") == "pending":
            jobs = [_job("fresh")]
        elif app.get("legacy"):
            jobs = [_job("regenerate")]
        else:
            app_drift = drift.get("apps", {}).get(app_id, {})
            stale = sorted(app_drift.get("stale_sections", {}))
            template = dt.app_template(dt.load_json(app_file(repo, app_id)), state) if app_file(repo, app_id).exists() else dt.TEMPLATE_VERSION
            regenerate = False
            if template == 3 and stale and not upgrade_now:
                jobs.append(_job("facts"))                  # writers only know template 4 (pipeline §5)
            if upgrade_now:
                for p in info["upgrade"]:
                    if app_id not in p.get("apps", [app_id]):
                        continue
                    if p["action"] in ("extend", "facts"):
                        jobs.append(_job(p["action"], sections=p.get("sections")))
                    elif p["action"] == "regenerate":
                        jobs.append(_job("regenerate"))
                        regenerate = True
            if info.get("split_flip") and answers.get("split") == "regenerate-split" and not regenerate:
                jobs.append(_job("regenerate", split="forced"))
                regenerate = True
            if (stale or app.get("fsm_new")) and not regenerate:
                jobs.append(_job("update", stale=stale, fsm_new=bool(app.get("fsm_new"))))
            if upgrade_now:
                sections = dt.load_json(app_file(repo, app_id)).get("sections", {}) if app_file(repo, app_id).exists() else {}
                drew = {s.get("diagram") for s in sections.values()}
                for p in info["upgrade"]:
                    if p["action"] == "redraw":
                        if "drawio" in drew and run["env"]["diagram_mode"] != "drawio":
                            info["notes"].append("%s: diagrams are draw.io, this run is Mermaid: redraw skipped, rerun with `drawio`" % app_id)
                        else:
                            jobs.append(_job("redraw"))
                    elif p["action"] == "restory":
                        jobs.append(_job("restory"))
                    elif p["action"] == "rehumanize":
                        jobs.append(_job("rehumanize"))
        if jobs:
            app["jobs"] = jobs
        else:
            app.pop("jobs", None)
    dt.save_json(state_path(repo), state)
    ensure_ignore(repo)


def ensure_ignore(repo):
    ignore = Path(repo) / dt.DOCS_DIR / ".docgen" / ".gitignore"
    current = ignore.read_text() if ignore.exists() else ""
    if ".work/" not in current:
        ignore.parent.mkdir(parents=True, exist_ok=True)
        ignore.write_text(current + ".work/\n")


def questions(run):
    out = []
    dirty = [(i["name"], i["meta"]["dirty_files"]) for i in run["repos"].values() if i["meta"].get("dirty") and not i.get("skip")]
    if dirty and "dirty" not in run["answers"]:
        listing = "; ".join("%s: %s" % (n, ", ".join(f[:5]) + (" …" if len(f) > 5 else "")) for n, f in dirty)
        out.append({"id": "dirty", "header": "Uncommitted", "question": "These repos have uncommitted changes (%s). Sections built on changed files get marked `+ uncommitted changes` and count as stale next time. Go on?" % listing,
                    "options": [{"value": "continue", "label": "Continue all"}, {"value": "commit-first", "label": "Commit first", "description": "Stop now; commit and run again"}],
                    "unattended": "continue"})
    upgrades = [(i["name"], p) for i in run["repos"].values() for p in i.get("upgrade", [])]
    if upgrades and "upgrade" not in run["answers"]:
        total = sum(p["tokens"] for _, p in upgrades)
        listing = "; ".join("%s: %s (%s, ~%dk tokens)" % (n, p["what"], p["units"], p["tokens"] // 1000) for n, p in upgrades)
        out.append({"id": "upgrade", "header": "Upgrade", "question": "The plugin's rules are newer than these docs: %s. Total about %dk tokens. Upgrade now?" % (listing, total // 1000),
                    "options": [{"value": "now", "label": "Upgrade now"}, {"value": "not-now", "label": "Not now", "description": "Fix real drift only; asked again next run"}],
                    "unattended": "not-now"})
    flips = [i["name"] for i in run["repos"].values() if i.get("split_flip")]
    if flips and "split" not in run["answers"]:
        out.append({"id": "split", "header": "Split", "question": "%s now has more than 10 apps, so every app's docs should be split into one file per section. That regenerates every documented app (about 150k tokens each). Do it now?" % ", ".join(flips),
                    "options": [{"value": "regenerate-split", "label": "Regenerate split"}, {"value": "not-now", "label": "Not now"}],
                    "unattended": "not-now"})
    legacy = ["%s/%s" % (i["name"], a) for i in run["repos"].values() for a in i.get("legacy", [])]
    if legacy and "legacy" not in run["answers"]:
        out.append({"id": "legacy", "header": "Unfinished", "question": "These apps were left mid-run by app-docs 2.x, whose stages 3.0 doesn't continue: %s. Start them fresh (their partial work is redone), or stop and finish them with app-docs 2.10.3?" % ", ".join(legacy),
                    "options": [{"value": "start-fresh", "label": "Start fresh"}, {"value": "stop", "label": "Stop", "description": "Reinstall 2.10.3, finish, then upgrade"}],
                    "unattended": "stop"})
    return out


def plan(run):
    """Re-plan every repo until nothing is left to ask or classify; returns an ask/classify/stop action or None."""
    for key in run["order"]:
        info = run["repos"][key]
        if info.get("planned") or info.get("skip"):
            continue
        info.pop("classify", None)
        plan_repo(Path(key), run)
        if not info.get("classify") and not (info.get("legacy") and run["answers"].get("legacy") != "start-fresh"):
            info["planned"] = True
    asks = questions(run)
    if run.get("unattended"):
        for q in asks:
            run["answers"][q["id"]] = q["unattended"]
            run["notes"].append("unattended: answered %s = %s" % (q["id"], q["unattended"]))
        if asks:
            for info in run["repos"].values():
                info.pop("planned", None)
            return plan(run)
        asks = []
    if run["answers"].get("dirty") == "commit-first":
        return {"action": "stop", "say": "Stopped: commit (or stash) the changes, then run again."}
    if run["answers"].get("legacy") == "stop":
        return {"action": "stop", "say": "Stopped: apps left mid-run by app-docs 2.x. Reinstall 2.10.3 (`claude plugin install app-docs@app-docs` at that version), finish them, then upgrade."}
    if asks:
        return {"action": "ask", "questions": [{k: v for k, v in q.items() if k != "unattended"} for q in asks],
                "answer_with": "python3 %s answer --root %s <id>=<value> …" % (HERE / "pipeline.py", run["root"])}
    pending = [{"repo": key, "candidates": info["classify"]} for key, info in run["repos"].items() if info.get("classify")]
    if pending:
        return {"action": "classify", "repos": pending,
                "rules": "Every candidate is an app (backends, frontends, workers, CLIs, libraries); a frontend and a backend are always separate apps. "
                         "Drop only containers with no code of their own (a package.json with `workspaces` whose packages are listed separately, a Maven `pom` aggregator) "
                         "and tooling nested inside another app (a package.json that only runs linters inside a Go service). Use suggested_id as the id. "
                         "Guess kind: backend | frontend | worker | cli | library.",
                "answer_with": "python3 %s apps --root %s --json '{\"<repo>\": [{\"path\": \"…\", \"id\": \"…\", \"kind\": \"…\"}]}'" % (HERE / "pipeline.py", run["root"])}
    return None


# ---------------------------------------------------------------- the app list and the start budget

def app_order(run):
    """(repo, app id) in run order: repos callees first, apps by id."""
    out = []
    for key in run["order"]:
        state = load_state(key)
        if state:
            out += [(key, a) for a in sorted(state.get("apps", {}))]
    return out


def begin_jobs(run):
    """Move apps with planned jobs into work, up to --max-apps (apps already working count first)."""
    limit = run["options"].get("max_apps")
    started = run.setdefault("started", [])
    for key, app_id in app_order(run):
        state = load_state(key)
        app = state["apps"][app_id]
        tag = "%s::%s" % (key, app_id)
        if app.get("job") and tag not in started:
            started.append(tag)
    for key, app_id in app_order(run):
        state = load_state(key)
        app = state["apps"][app_id]
        tag = "%s::%s" % (key, app_id)
        if app.get("job") or not app.get("jobs"):
            continue
        if limit is not None and len(started) >= limit:
            if tag not in run.setdefault("deferred", []):
                run["deferred"].append(tag)
            continue
        if tag in run.get("deferred", []):
            run["deferred"].remove(tag)
        start_next_job(key, app_id, state)
        started.append(tag)


def start_next_job(repo, app_id, state=None):
    state = state or load_state(repo)
    app = state["apps"][app_id]
    job = app["jobs"].pop(0)
    if app.pop("fsm_new", False) and job["name"] == "update":
        job["fsm_new"] = True
    app.pop("legacy", None)
    app.update(job=job, step=STEPS[job["name"]][0], stage="working", stage_at=now(), job_started=now(), flows_done=[])
    app.pop("stage_error", None)
    app.pop("flows_todo", None)
    if not app["jobs"]:
        app.pop("jobs")
    dt.save_json(state_path(repo), state)


def set_app(repo, app_id, **fields):
    state = load_state(repo)
    app = state["apps"][app_id]
    for k, v in fields.items():
        if v is None:
            app.pop(k, None)
        else:
            app[k] = v
    app["stage_at"] = now()
    dt.save_json(state_path(repo), state)
    return app


# ---------------------------------------------------------------- agent prompts

def reading_list(agent, mode, run, fsm):
    """The reference files each agent reads, per mode: only what that mode needs."""
    drawio = run["env"]["diagram_mode"] == "drawio"
    diagram_rules = ["diagrams-spec.md", "spec-examples/ (the closest example only)"] if drawio else ["diagrams-style.md"]
    if agent == "app-documenter":
        lists = {
            "app": ["conventions.md", "state-schema.md", "facts-schema.md", "dev-guide-template.md", "operator-guide-template.md",
                    "diagrams.md", "diagrams-app.md"] + diagram_rules[:1] + (["state-machines.md"] if fsm else []),
            "extend": ["conventions.md §2–5, §8, §11, §12", "facts-schema.md", "operator-guide-template.md (only the sections named below)"],
            "facts": ["facts-schema.md", "conventions.md §5"],
            "redraw": ["diagrams.md", "diagrams-app.md"] + diagram_rules[:1],
        }
        lists["update"] = lists["app"]
        return lists[mode]
    lists = {
        "flow": ["conventions.md §3–7, §12", "flow-template.md", "facts-schema.md (Rules, flow_details, logs)", "diagrams.md", "diagrams-flow.md"] + diagram_rules,
        "story": ["conventions.md §5", "flow-template.md (the story parts)", "diagrams.md §5"],
        "redraw": ["diagrams.md", "diagrams-flow.md", "flow-template.md (the story parts)"] + diagram_rules,
    }
    return lists[mode]


def header(repo, run):
    meta = dict(run["repos"][str(repo)]["meta"])
    for k in ("dirty_files", "template_version", "humanizer_version", "diagram_version", "story_version", "windows_drive"):
        meta.pop(k, None)
    return "\n".join([
        "Repo root: %s" % repo,
        "Shared folder: %s" % SHARED,
        "Meta: %s" % json.dumps(meta, ensure_ascii=False),
        "Diagram mode: %s   Draw.io skill: %s" % (run["env"]["diagram_mode"], run["env"].get("drawio_skill") or "none"),
    ])


def gitlab_doc_url(repo, path):
    base = run_meta_cache.get(str(repo)) or dt.web_url(repo)
    run_meta_cache[str(repo)] = base
    return "%s/-/blob/HEAD/%s" % (base, path) if base else None


run_meta_cache = {}


def other_apps(repo, app_id, run):
    """Cross-app link targets (conventions §12): same repo as relative paths, other repos as GitLab links."""
    lines = []
    for key in run["order"]:
        state = load_state(key) or {"apps": {}}
        for other, entry in sorted(state["apps"].items()):
            if key == str(repo) and other == app_id:
                continue
            path = app_file(key, other)
            docs = dt.load_json(path).get("docs", {}) if path.exists() else {}
            planned = entry.get("stage") == "done" or entry.get("job") or entry.get("jobs")
            if not docs and planned:
                docs = {"dev": "docs/%s/dev-guide.md" % other, "operator": "docs/%s/operator-guide.md" % other}
            if not docs:
                lines.append("- %s%s: not documented yet" % ("" if key == str(repo) else Path(key).name + "/", other))
            elif key == str(repo):
                lines.append("- %s (this repo): Dev Guide `%s` · User Guide `%s`" % (other, docs["dev"], docs["operator"]))
            else:
                dev, op = gitlab_doc_url(key, docs["dev"]), gitlab_doc_url(key, docs["operator"])
                lines.append("- %s/%s (another repo): Dev Guide %s · User Guide %s" % (Path(key).name, other, dev or "(no GitLab remote)", op or "(no GitLab remote)"))
    return "\n".join(lines) or "none"


def app_prompt(repo, app_id, job, run):
    state = load_state(repo)
    app = state["apps"][app_id]
    mode = APP_MODE[job["name"]]
    fsm = bool(app.get("fsm"))
    split = "forced (repo has >10 apps)" if state.get("split_all") or job.get("split") else "decide by conventions §10"
    lines = [header(repo, run),
             "Mode: %s" % mode,
             "App: id=%s root=%s kind=%s" % (app_id, app.get("root"), app.get("kind") or "guess"),
             "FSM: %s" % ("on" if fsm else "off"),
             "Split: %s" % split,
             "Repo template version: %s" % state.get("template_version"),
             "Reading list (under the Shared folder's references/; nothing else from there): %s" % "; ".join(reading_list("app-documenter", "update" if mode == "update" else mode, run, fsm)),
             "Other apps (cross-app links, conventions §12):\n%s" % other_apps(repo, app_id, run)]
    if mode == "update":
        drift = tool(repo, "drift").get("apps", {}).get(app_id, {})
        lines.append("Drift: %s" % json.dumps(drift, ensure_ascii=False))
        lines.append("Template changed: %s   FSM newly enabled: %s" % ("yes" if job["name"] == "regenerate" else "no", "yes" if job.get("fsm_new") else "no"))
    if mode == "extend":
        lines.append("Add these sections and nothing else: %s" % json.dumps(job.get("sections"), ensure_ascii=False))
    lines.append("Write: per your mode. Return a summary of 10 lines or fewer.")
    return "\n".join(lines)


def flow_prompt(repo, brief, mode, run, fsm):
    return "\n".join([header(repo, run), "Mode: %s" % mode, "Brief: %s" % brief,
                      "Reading list (under the Shared folder's references/; nothing else from there): %s" % "; ".join(reading_list("flow-documenter", mode, run, fsm))])


def review_prompt(repo, app_id, scope):
    return "\n".join(["Repo root: %s" % repo, "Shared folder: %s" % SHARED,
                      "App state: %s" % rel(repo, app_file(repo, app_id)),
                      "Review scope: %s" % ("all sections" if scope is None else ", ".join(scope)),
                      "Write findings to: %s" % (WORK / ("review-%s.json" % app_id)).as_posix()])


def fixer_prompt(repo, app_id):
    return "\n".join(["Repo root: %s" % repo, "Shared folder: %s" % SHARED,
                      "App state: %s" % rel(repo, app_file(repo, app_id)),
                      "Findings: %s" % (WORK / ("review-%s.json" % app_id)).as_posix()])


def humanizer_prompt(repo, app_id, run, restore=None):
    lines = ["Repo root: %s" % repo, "Shared folder: %s" % SHARED,
             "App state: %s" % rel(repo, app_file(repo, app_id)),
             "Plan: %s" % (WORK / ("humanize-%s-plan.json" % app_id)).as_posix(),
             "humanizer-indonesia skill: %s" % (run["env"].get("humanizer_skill") or "none")]
    if restore:
        lines.append("Facts to restore: %s" % json.dumps(restore, ensure_ascii=False))
    return "\n".join(lines)


# ---------------------------------------------------------------- tasks

def add_task(run, repo, app_id, agent, prompt, step, **extra):
    n = sum(1 for t in run["tasks"].values() if t["repo"] == str(repo) and t["app"] == app_id) + 1
    task_id = "%s/%s/%s-%d" % (Path(repo).name, app_id, step, n)
    run["tasks"][task_id] = dict(extra, repo=str(repo), app=app_id, agent=agent, prompt=prompt, step=step,
                                 status="queued", created=now())
    return task_id


def step_tasks(run, repo, app_id, step):
    return [t for t in run["tasks"].values() if t["repo"] == str(repo) and t["app"] == app_id and t["step"] == step
            and t.get("job_seq") == job_seq(repo, app_id)]


def job_seq(repo, app_id):
    """Tasks belong to one job of one app; a later job of the same app starts with no tasks."""
    app = load_state(repo)["apps"][app_id]
    return "%s@%s" % ((app.get("job") or {}).get("name"), app.get("job_started"))


def app_snapshot(repo, app_id):
    """Hash of every section's text, to find the sections a job changed (the review and humanizer scope)."""
    app_state = dt.load_json(app_file(repo, app_id))
    sections = dt._app_sections(Path(repo), app_state)
    return {"%s:%s" % (kind, sid): hashlib.sha256(text.encode()).hexdigest()[:16] for kind, secs in sections.items() for sid, text in secs.items()}


def flows_for(repo, app_id, job):
    app_state = dt.load_json(app_file(repo, app_id))
    important = [f["id"] for f in app_state.get("flows", []) if f.get("important") and f.get("status", "active") == "active"]
    if job["name"] != "update":
        return important
    stale = {k.split("/", 1)[1] for k in job.get("stale", []) if k.split(":", 1)[1].startswith("app-flow/")}
    sections = app_state.get("sections", {})
    return [f for f in important if f in stale or "dev:app-flow/%s" % f not in sections]


# ---------------------------------------------------------------- advancing one app

def report_of(run, repo, app_id):
    return run["report"].setdefault(str(repo), {}).setdefault(app_id, {"validator": [], "notes": [], "problems": []})


def add_problem(run, repo, app_id, text):
    problems = report_of(run, repo, app_id)["problems"]
    if text not in problems:
        problems.append(text)


def advance(run, repo, app_id):
    """Run script steps and create agent tasks for one app until it waits on an agent. Returns True if anything moved."""
    moved = False
    while True:
        state = load_state(repo)
        app = state["apps"][app_id]
        job = app.get("job")
        if not job or app.get("stage") == "failed":
            return moved
        step = app["step"]
        handler = STEP_HANDLERS[step]
        result = handler(run, repo, app_id, job)
        if result == "wait":
            return moved
        moved = True
        if result == "failed":
            return moved
        next_step(run, repo, app_id)


def next_step(run, repo, app_id):
    state = load_state(repo)
    app = state["apps"][app_id]
    steps = STEPS[app["job"]["name"]]
    i = steps.index(app["step"])
    if i + 1 < len(steps):
        set_app(repo, app_id, step=steps[i + 1])
        return
    if app.get("jobs"):
        start_next_job(repo, app_id)
        return
    set_app(repo, app_id, stage="done", job=None, step=None, flows_todo=None, flows_done=None, job_started=None)
    report_of(run, repo, app_id)["status"] = "done"


def fail_app(run, repo, app_id, why):
    set_app(repo, app_id, stage="failed", stage_error=why)
    r = report_of(run, repo, app_id)
    r["status"] = "failed"
    r["error"] = "%s (at %s)" % (why, load_state(repo)["apps"][app_id].get("step"))


def ensure_job_start(run, repo, app_id):
    """Once per job: the keep-block snapshot (once per run) and the section snapshot for the scope."""
    marker = "%s::%s" % (repo, app_id)
    if marker not in run.setdefault("kept", []) and app_file(repo, app_id).exists():
        tool(repo, "keep-snapshot", "--app-state", rel(repo, app_file(repo, app_id)), "--out", str(in_work(repo, "keep-%s.json" % app_id)))
        run["kept"].append(marker)
    before = in_work(repo, "sections-before-%s.json" % app_id)
    if not before.exists() or dt.load_json(before).get("job") != job_seq(repo, app_id):
        dt.save_json(before, {"job": job_seq(repo, app_id), "sections": app_snapshot(repo, app_id) if app_file(repo, app_id).exists() else {}})


def keep_restore(run, repo, app_id):
    snap = Path(repo) / WORK / ("keep-%s.json" % app_id)
    if not snap.exists():
        return                       # documented for the first time in this run: nothing was there to keep
    out = tool(repo, "keep-restore", "--app-state", rel(repo, app_file(repo, app_id)), "--before", str(snap))
    if out.get("restored"):
        report_of(run, repo, app_id)["notes"].append("keep blocks put back after an agent dropped them: %s" % ", ".join(out["restored"]))


def scope(repo, app_id, job):
    """None for the whole guide, else the section keys this job changed."""
    if job["name"] in WHOLE_GUIDE:
        return None
    before = dt.load_json(Path(repo) / WORK / ("sections-before-%s.json" % app_id)).get("sections", {})
    after = app_snapshot(repo, app_id)
    return sorted(k for k, v in after.items() if before.get(k) != v)


# Each step handler returns "next" (step finished), "wait" (an agent task is queued or running) or "failed".

def step_app(run, repo, app_id, job):
    ensure_job_start(run, repo, app_id)
    tasks = step_tasks(run, repo, app_id, "app")
    if not tasks:
        add_task(run, repo, app_id, "app-documenter", app_prompt(repo, app_id, job, run), "app", job_seq=job_seq(repo, app_id),
                 description="%s: %s (%s)" % (app_id, "document app" if job["name"] == "fresh" else job["name"], Path(repo).name))
        return "wait"
    if any(t["status"] in ("queued", "running") for t in tasks):
        return "wait"
    if any(t["status"] == "failed" for t in tasks):
        fail_app(run, repo, app_id, next(t.get("error") for t in tasks if t["status"] == "failed") or "app-documenter failed")
        return "failed"
    keep_restore(run, repo, app_id)
    problem = verify_app(repo, app_id, job)
    if problem:
        fail_app(run, repo, app_id, problem)
        return "failed"
    return "next"


def verify_app(repo, app_id, job):
    path = app_file(repo, app_id)
    try:
        app_state = dt.load_json(path)
    except (OSError, ValueError):
        return "app-documenter finished without a readable app state (%s)" % rel(repo, path)
    if job["name"] == "facts":
        return None if app_state.get("template_version") == 4 else "facts conversion didn't finish (template_version isn't 4)"
    if job["name"] in ("fresh", "update", "regenerate"):
        docs = app_state.get("docs", {})
        missing = [d for d in ("dev", "operator") if not docs.get(d) or not (Path(repo) / docs[d]).exists()]
        if missing or "flows" not in app_state:
            return "app-documenter finished without %s" % ("its flows" if "flows" not in app_state else "the %s guide" % " and ".join(missing))
    if job["name"] == "extend":
        wanted = ["%s:%s" % (k, s) for k, ids in (job.get("sections") or {}).items() for s in ids]
        lost = [k for k in wanted if k not in app_state.get("sections", {})]
        if lost:
            return "extend didn't write %s" % ", ".join(lost)
    return None


def _flow_step(run, repo, app_id, job, mode, step):
    tasks = step_tasks(run, repo, app_id, step)
    app = load_state(repo)["apps"][app_id]
    if app.get("flows_todo") is None:
        set_app(repo, app_id, flows_todo=flows_for(repo, app_id, job))
        app = load_state(repo)["apps"][app_id]
    todo = [f for f in app["flows_todo"] if f not in app.get("flows_done", [])]
    if any(t["status"] in ("queued", "running") for t in tasks):
        return "wait"
    if tasks:
        # every task of this step finished: flows without a fragment are reported and left as placeholders
        missing = [f for f in todo]
        if missing:
            add_problem(run, repo, app_id, "flows not documented (their agent stopped early): %s" % ", ".join(missing))
            set_app(repo, app_id, stage_error="flows missing: %s" % ", ".join(missing))
        return "next"
    if not todo:
        return "next"
    briefs = tool(repo, "briefs", "--app-state", rel(repo, app_file(repo, app_id)), "--flows", ",".join(todo))
    for b in briefs.get("briefs", []):
        add_task(run, repo, app_id, "flow-documenter", flow_prompt(repo, b["brief"], mode, run, bool(app.get("fsm"))), step,
                 job_seq=job_seq(repo, app_id), flows=b["flows"],
                 description="%s: %s %s" % (app_id, {"flow": "flows", "story": "stories", "redraw": "redraw"}[mode], ",".join(b["flows"])[:40]))
    return "wait" if briefs.get("briefs") else "next"


def step_flows(run, repo, app_id, job):
    ensure_job_start(run, repo, app_id)
    return _flow_step(run, repo, app_id, job, FLOW_MODE[job["name"]], "flows")


def step_redraw(run, repo, app_id, job):
    """App diagrams and flow diagrams are redrawn at the same time: they're different files."""
    ensure_job_start(run, repo, app_id)
    tasks = step_tasks(run, repo, app_id, "redraw-app")
    if not tasks:
        add_task(run, repo, app_id, "app-documenter", app_prompt(repo, app_id, job, run), "redraw-app", job_seq=job_seq(repo, app_id),
                 description="%s: redraw app diagrams" % app_id)
    flows = _flow_step(run, repo, app_id, job, "redraw", "flows")
    if any(t["status"] in ("queued", "running") for t in step_tasks(run, repo, app_id, "redraw-app")) or flows == "wait":
        return "wait"
    keep_restore(run, repo, app_id)
    return "next"


def step_assemble(run, repo, app_id, job):
    state_rel = rel(repo, app_file(repo, app_id))
    out = tool(repo, "assemble", "--app-state", state_rel)
    for p in out.get("problems", []):
        add_problem(run, repo, app_id, "assemble %s: %s" % (p["flow"], p["error"]))
    keep_restore(run, repo, app_id)
    marker = "%s::%s" % (repo, app_id)
    refresh = marker not in run.setdefault("owners_refreshed", [])
    tool(repo, "render", "--app-state", state_rel, *(["--refresh-owners"] if refresh else []))
    if refresh:
        run["owners_refreshed"].append(marker)
    tool(repo, "facts-snapshot", "--app-state", state_rel, "--out", str(in_work(repo, "facts-%s-draft.json" % app_id)))
    return "next"


def step_review(run, repo, app_id, job):
    sc = scope(repo, app_id, job)
    if sc is not None and not sc:
        return "next"
    tasks = step_tasks(run, repo, app_id, "review")
    findings = Path(repo) / WORK / ("review-%s.json" % app_id)
    if not tasks:
        if findings.exists():
            findings.unlink()                 # a review from an earlier job must not count as this one
        add_task(run, repo, app_id, "goldfish-reviewer", review_prompt(repo, app_id, sc), "review", job_seq=job_seq(repo, app_id),
                 description="%s: review" % app_id)
        return "wait"
    if any(t["status"] in ("queued", "running") for t in tasks):
        return "wait"
    try:
        data = dt.load_json(findings)
        assert isinstance(data.get("findings"), list)
    except (OSError, ValueError, AssertionError):
        fail_app(run, repo, app_id, "the review wrote no findings file (%s); the next run reviews again" % (WORK / findings.name).as_posix())
        return "failed"
    counts = {}
    for f in data["findings"]:
        counts[f.get("severity", "?")] = counts.get(f.get("severity", "?"), 0) + 1
    report_of(run, repo, app_id)["review"] = {"findings": len(data["findings"]), "by_severity": counts}
    return "next"


def step_fix(run, repo, app_id, job):
    findings = Path(repo) / WORK / ("review-%s.json" % app_id)
    if not findings.exists() or not dt.load_json(findings).get("findings"):
        return "next"
    tasks = step_tasks(run, repo, app_id, "fix")
    if not tasks:
        add_task(run, repo, app_id, "doc-fixer", fixer_prompt(repo, app_id), "fix", job_seq=job_seq(repo, app_id), description="%s: apply review" % app_id)
        return "wait"
    if any(t["status"] in ("queued", "running") for t in tasks):
        return "wait"
    if any(t["status"] == "failed" for t in tasks):
        add_problem(run, repo, app_id, "doc-fixer failed: findings not applied (%s)" % (WORK / findings.name).as_posix())
    state_rel = rel(repo, app_file(repo, app_id))
    keep_restore(run, repo, app_id)
    tool(repo, "render", "--app-state", state_rel)
    draft = Path(repo) / WORK / ("facts-%s-draft.json" % app_id)
    if draft.exists():
        diff = tool(repo, "facts-diff", "--app-state", state_rel, "--before", str(draft))
        if diff.get("changes"):
            report_of(run, repo, app_id)["fix_changed_facts"] = ["%s:%s lost %s, added %s" % (c["doc"], c["section"], c["lost"], c["added"]) for c in diff["changes"]][:10]
    return "next"


def step_humanize(run, repo, app_id, job):
    state_rel = rel(repo, app_file(repo, app_id))
    tasks = step_tasks(run, repo, app_id, "humanize")
    if not tasks:
        sc = scope(repo, app_id, job)
        if sc is not None:
            if job["name"] in ("redraw", "restory"):
                sc = [k for k in sc if k.startswith("op:app-flow/")]
            sc = [k for k in sc if k.startswith("op:")]
            if not sc:
                return "next"
        plan_out = tool(repo, "humanize-plan", "--app-state", state_rel, "--skill", run["env"].get("humanizer_skill") or "none",
                        *(["--scope", ",".join(sc)] if sc else []))
        if not plan_out.get("paragraphs") and not plan_out.get("facts_strings"):
            return "next"
        tool(repo, "facts-snapshot", "--app-state", state_rel, "--out", str(in_work(repo, "facts-%s-prehuman.json" % app_id)))
        add_task(run, repo, app_id, "operator-humanizer", humanizer_prompt(repo, app_id, run), "humanize", job_seq=job_seq(repo, app_id),
                 pass_no=1, description="%s: humanize User Guide" % app_id)
        return "wait"
    if any(t["status"] in ("queued", "running") for t in tasks):
        return "wait"
    keep_restore(run, repo, app_id)
    tool(repo, "render", "--app-state", state_rel)
    diff = tool(repo, "facts-diff", "--app-state", state_rel, "--before", str(Path(repo) / WORK / ("facts-%s-prehuman.json" % app_id)), "--only", "op", "--strict")
    if diff.get("changes"):
        if len(tasks) == 1:
            add_task(run, repo, app_id, "operator-humanizer", humanizer_prompt(repo, app_id, run, restore=diff["changes"]), "humanize",
                     job_seq=job_seq(repo, app_id), pass_no=2, description="%s: humanizer, restore facts" % app_id)
            return "wait"
        report_of(run, repo, app_id)["validator"].append("humanizer-fact-changed: %s" % "; ".join(
            "%s lost %s added %s" % (c["section"], c["lost"], c["added"]) for c in diff["changes"])[:300])
    return "next"


def step_finish(run, repo, app_id, job):
    state_rel = rel(repo, app_file(repo, app_id))
    if job["name"] != "facts":
        tool(repo, "svg-theme", "--app", app_id)
        tool(repo, "stamp", "--app-state", state_rel)
    out = tool(repo, "validate", "--app-state", state_rel)
    r = report_of(run, repo, app_id)
    r["validator"] = [v for v in r["validator"] if v.startswith("humanizer-")] + [
        "%s: %s" % (f["rule"], f["message"]) for f in out.get("failures", [])]
    r["warnings"] = [w for w in out.get("warnings", []) if w.startswith("fact-mismatch")][:10]
    r["stats"] = out.get("stats")
    r.setdefault("jobs", []).append(job["name"])
    return "next"


STEP_HANDLERS = {"app": step_app, "flows": step_flows, "redraw": step_redraw, "assemble": step_assemble, "review": step_review,
                 "fix": step_fix, "humanize": step_humanize, "finish": step_finish}


# ---------------------------------------------------------------- task completion

def verify_flows(repo, app_id, task):
    """Flows whose fragment is complete (its state.json is written last) or already assembled."""
    finished = []
    for flow in task.get("flows", []):
        if (Path(repo) / WORK / "fragments" / app_id / flow / "state.json").exists():
            finished.append(flow)
    return finished


def complete(run, task_id, error=None):
    task = run["tasks"].get(task_id)
    if task is None:
        raise Stop("unknown task %s" % task_id)
    if task["status"] in ("done", "failed"):
        return
    task["status"] = "failed" if error else "done"
    task["finished"] = now()
    if error:
        task["error"] = error
    repo, app_id = Path(task["repo"]), task["app"]
    if task["agent"] == "flow-documenter":
        finished = verify_flows(repo, app_id, task)
        if finished:
            state = load_state(repo)
            done = state["apps"][app_id].setdefault("flows_done", [])
            done += [f for f in finished if f not in done]
            dt.save_json(state_path(repo), state)


def recover(run):
    """After an interruption, a task left "running" either finished on disk or is queued again."""
    for task_id, task in run["tasks"].items():
        if task["status"] != "running":
            continue
        repo, app_id = Path(task["repo"]), task["app"]
        if task["agent"] == "flow-documenter":
            finished = verify_flows(repo, app_id, task)
            if set(finished) == set(task.get("flows", [])):
                complete(run, task_id)
                continue
            # rewrite the brief for the flows still missing, so the agent doesn't redo finished ones
            complete(run, task_id)
            state = load_state(repo)
            app = state["apps"][app_id]
            app["flows_done"] = sorted(set(app.get("flows_done", [])) | set(finished))
            dt.save_json(state_path(repo), state)
            missing = [f for f in task["flows"] if f not in finished]
            briefs = tool(repo, "briefs", "--app-state", rel(repo, app_file(repo, app_id)), "--flows", ",".join(missing))
            mode = task["prompt"].split("Mode: ", 1)[1].split("\n", 1)[0]
            for b in briefs.get("briefs", []):
                add_task(run, repo, app_id, "flow-documenter", flow_prompt(repo, b["brief"], mode, run, bool(app.get("fsm"))), task["step"],
                         job_seq=task.get("job_seq"), flows=b["flows"], description="%s: flows %s (resumed)" % (app_id, ",".join(b["flows"])[:40]))
            continue
        if task["agent"] == "goldfish-reviewer":
            try:
                if isinstance(dt.load_json(Path(repo) / WORK / ("review-%s.json" % app_id)).get("findings"), list):
                    complete(run, task_id)
                    continue
            except (OSError, ValueError):
                pass
        task["status"] = "queued"       # app agents, the fixer and the humanizer pick up their own partial work


# ---------------------------------------------------------------- the next action

def next_action(path, run):
    pending = plan(run)
    if pending:
        save_run(path, run)
        return pending
    begin_jobs(run)
    moved = True
    while moved:
        moved = False
        for key, app_id in app_order(run):
            app = load_state(key)["apps"][app_id]
            if app.get("job") and app.get("stage") == "working":
                moved |= advance(run, Path(key), app_id)
    running = [t for t in run["tasks"].values() if t["status"] == "running"]
    launch = []
    order = {tag: i for i, tag in enumerate("%s::%s" % pair for pair in app_order(run))}
    queued = sorted((t for t in run["tasks"].items() if t[1]["status"] == "queued"),
                    key=lambda item: (order.get("%s::%s" % (item[1]["repo"], item[1]["app"]), 0), item[1]["created"]))
    for task_id, task in queued[: max(0, PARALLEL - len(running))]:
        task["status"] = "running"
        task["launched"] = now()
        launch.append({"task": task_id, "subagent_type": task["agent"], "description": task["description"], "prompt": task["prompt"]})
    save_run(path, run)
    if launch:
        return {"action": "agents", "launch": launch, "running": [t for t, v in run["tasks"].items() if v["status"] == "running" and t not in {l["task"] for l in launch}],
                "report_with": "python3 %s done --root %s --task <id> [--task <id>…] [--failed <id> --error \"<why>\"]" % (HERE / "pipeline.py", run["root"])}
    if running:
        return {"action": "wait", "running": [t for t, v in run["tasks"].items() if v["status"] == "running"]}
    return finish(path, run)


def finish(path, run):
    for key in run["order"]:
        state = load_state(key)
        if not state or run["answers"].get("upgrade") != "now":
            continue
        apps = state.get("apps", {})
        if all(a.get("stage") == "done" for a in apps.values()):
            versions = [dt.app_template(dt.load_json(app_file(key, a)), state) for a in apps if app_file(key, a).exists()]
            state["template_version"] = min(versions) if versions else dt.TEMPLATE_VERSION
            state.update(humanizer_version=dt.HUMANIZER_VERSION, diagram_version=dt.DIAGRAM_VERSION, story_version=dt.STORY_VERSION)
            dt.save_json(state_path(key), state)
    run["finished"] = now()
    spend = None
    proc = subprocess.run([sys.executable, str(TOOL), "usage-spend", "--repo", run["root"], "--since", run["run"]],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)
    try:
        spend = json.loads(proc.stdout)
    except ValueError:
        pass
    report = report_text(run, spend)
    save_run(path, run)
    return {"action": "done", "say": report}


def report_text(run, spend):
    lines = []
    for note in run.get("notes", []) + run["env"].get("notes", []):
        lines.append("Note: %s" % note)
    changed = False
    for key in run["order"]:
        info = run["repos"][key]
        state = load_state(key) or {"apps": {}}
        rows = []
        for app_id, app in sorted(state["apps"].items()):
            r = run["report"].get(key, {}).get(app_id)
            if r is None and app.get("stage") == "done":
                continue
            r = r or {}
            changed |= bool(r.get("jobs"))
            if app.get("stage") == "failed":
                rows.insert(0, "%s  ❌ failed at %s: %s" % (app_id, app.get("step"), app.get("stage_error")))
                continue
            if app.get("stage") != "done":
                rows.append("%s  ⏸ not finished (%s at %s): run again to continue" % (app_id, (app.get("job") or {}).get("name") or "queued", app.get("step") or "start"))
                continue
            app_state = dt.load_json(app_file(key, app_id))
            flows = app_state.get("flows", [])
            row = ["%s  ✅ %s  %s  (%s, %d flows, %d full)" % (app_id, "+".join(r.get("jobs", [])) or "done", Path(app_state["docs"]["dev"]).parent.as_posix(),
                                                            "split" if Path(key, app_state["docs"]["dev"]).is_dir() else "single", len(flows),
                                                            sum(1 for f in flows if f.get("important")))]
            if r.get("validator"):
                row.append("  Validator: %d failures" % len(r["validator"]))
                row += ["    - %s" % v for v in r["validator"][:5]]
            if r.get("review"):
                row.append("  Goldfish: %d findings %s" % (r["review"]["findings"], json.dumps(r["review"]["by_severity"])))
            if r.get("fix_changed_facts"):
                row.append("  Fix changed facts: %s" % "; ".join(r["fix_changed_facts"][:3]))
            if r.get("warnings"):
                row.append("  Guides disagree: %s" % "; ".join(r["warnings"][:3]))
            for p in r.get("problems", []) + r.get("notes", []):
                row.append("  %s" % p)
            rows += row
        deferred = [t.split("::", 1)[1] for t in run.get("deferred", []) if t.startswith(key + "::")]
        if deferred:
            rows.append("Not started (--max-apps): %s. Run again to continue." % ", ".join(deferred))
        if rows or info["notes"]:
            lines.append("## %s" % info["name"])
            lines += ["Note: %s" % n for n in info["notes"]]
            lines += rows
    if spend and spend.get("by_model"):
        lines.append("Spend since %s: %s" % (run["run"], " · ".join(
            "%s %dk out · %dk cache read · %dk cache write · %dk in" % (m, v["output"] // 1000, v["cache_read"] // 1000, v["cache_write"] // 1000, v["input"] // 1000)
            for m, v in sorted(spend["by_model"].items()))))
        main = [a for a in spend.get("agents", []) if not a.get("subagent")]
        if main:
            lines.append("Main session model: %s" % ", ".join(sorted({a.get("model") or "?" for a in main})))
    elif spend is not None:
        lines.append("Spend: no session transcripts found (%s)" % spend.get("error", "")[:120])
    lines.append("Nothing was committed: review the diff under docs/ (and state.json) and commit.")
    if changed:
        lines.append("To publish the User Guides to Docmost, run `/app-docs:sync` in a **new** conversation.")
    return "\n".join(lines)


# ---------------------------------------------------------------- commands

def retry_failed(run, repos):
    """A failed app resumes at the step that failed: its failed tasks are set aside so the step starts over."""
    for repo in repos:
        state = load_state(repo)
        for app_id, app in (state or {}).get("apps", {}).items():
            if app.get("stage") == "failed" and app.get("job"):
                app["stage"] = "working"
                steps = ("redraw-app", "flows") if app.get("step") == "redraw" else (app.get("step"),)
                for task in run["tasks"].values():
                    if task["repo"] == str(repo) and task["app"] == app_id and (task["status"] == "failed" or task["step"] in steps):
                        task["status"], task["job_seq"] = "retried", None
                run["report"].get(str(repo), {}).pop(app_id, None)
        if state:
            dt.save_json(state_path(repo), state)


def cmd_start(args):
    kind, repos = discover(args.root)
    root = Path(args.root).resolve() if kind == "workspace" else repos[0]
    path = run_file(root, kind)
    old = dt.load_json(path) if path.exists() else None
    if kind == "workspace":
        repos, _ = sync_workspace(root, repos)
    options = {"drawio": args.drawio, "fsm": args.fsm, "max_apps": args.max_apps}
    if old and not old.get("finished") and old.get("command") == args.command:
        run = old
        run["options"].update({k: v for k, v in options.items() if v})
        run["unattended"] = args.unattended
        recover(run)
        run["notes"] = [n for n in run.get("notes", []) if not n.startswith("Resumed")] + ["Resumed the run started %s" % run["run"]]
    else:
        run = {"version": 3, "run": now(), "command": args.command, "root": str(root), "kind": kind, "options": options,
               "unattended": args.unattended, "answers": {}, "tasks": {}, "report": {}, "notes": [], "repos": {}}
    run["env"] = environment(repos, args.drawio or (old or {}).get("options", {}).get("drawio"))
    retry_failed(run, repos)
    run["order"] = [str(r) for r in repos]
    for r in repos:
        notes = preflight(r, run)
        if str(r) in run["repos"]:
            run["repos"][str(r)].update(meta=notes["meta"], notes=notes["notes"], planned=False)
        else:
            run["repos"][str(r)] = notes
    print(json.dumps(next_action(path, run), ensure_ascii=False, indent=1))


def cmd_answer(args):
    path, run = load_run(args.root)
    for pair in args.pairs:
        key, _, value = pair.partition("=")
        run["answers"][key] = value
    for info in run["repos"].values():
        info["planned"] = False
    print(json.dumps(next_action(path, run), ensure_ascii=False, indent=1))


def cmd_apps(args):
    path, run = load_run(args.root)
    chosen = json.loads(args.json)
    for key, apps in chosen.items():
        match = next((k for k in run["repos"] if k == key or Path(k).name == key or k.endswith("/" + key)), None)
        if match is None:
            raise Stop("unknown repo %s" % key)
        run.setdefault("classified", {})[match] = apps
        run["repos"][match]["planned"] = False
    print(json.dumps(next_action(path, run), ensure_ascii=False, indent=1))


def cmd_done(args):
    path, run = load_run(args.root)
    for task_id in args.task or []:
        complete(run, task_id)
    if args.failed:
        complete(run, args.failed, error=args.error or "agent failed")
    print(json.dumps(next_action(path, run), ensure_ascii=False, indent=1))


def cmd_next(args):
    path, run = load_run(args.root)
    print(json.dumps(next_action(path, run), ensure_ascii=False, indent=1))


def cmd_targets(args):
    """What a sync would do, per repo and app, without page contents: repos in run order (callees first, so
    most cross-service links resolve on the first pass), pages to create or update, links still waiting for
    their target page, orphans, and whether Docmost is calibrated yet."""
    kind, repos = discover(args.root)
    root = Path(args.root).resolve() if kind == "workspace" else repos[0]
    if kind == "workspace":
        repos, _ = sync_workspace(root, repos)
    out, root_url, calibrated, checks = [], None, False, set()
    for repo in repos:
        if not state_path(repo).exists():
            out.append({"repo": str(repo), "skip": "not documented: run /app-docs:generate first"})
            continue
        tool(repo, "migrate")
        try:
            plan = tool(repo, "sync-plan")
        except RuntimeError as error:
            out.append({"repo": str(repo), "error": str(error)})
            continue
        root_url = root_url or plan.get("root_url")
        calibrated = calibrated or bool(plan.get("method") and plan.get("image_method"))
        settings = dt.docmost_settings(repo, load_state(repo))
        if not settings.get("diagram_theme") and any(p["images"] or p["images_linked"] for p in plan["pages"]):
            checks.add("diagram theme")
        if not settings.get("list_numbers"):
            checks.add("list numbers")
        apps = {}
        for page in plan["pages"]:
            entry = apps.setdefault(page["key"].split("/", 1)[0], {"pages": 0, "to_sync": 0, "links_pending": 0})
            entry["pages"] += 1
            entry["to_sync"] += 1 if page["changed"] else 0
            entry["links_pending"] += len(page["links_pending"])
        out.append({"repo": str(repo), "apps": apps, "orphans": plan["orphans"],
                    "not_done": sorted(a for a, v in load_state(repo).get("apps", {}).items() if v.get("stage") != "done")})
    print(json.dumps({"kind": kind, "root": str(root), "root_url": root_url, "calibrated": calibrated,
                      "checks": sorted(checks) or ["none"], "repos": out,
                      "to_sync": sum(a["to_sync"] for r in out for a in r.get("apps", {}).values())}, ensure_ascii=False, indent=1))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start")
    p.add_argument("--root", default=".")
    p.add_argument("--command", choices=["generate", "update"], default="generate")
    p.add_argument("--drawio", action="store_true")
    p.add_argument("--fsm", action="store_true")
    p.add_argument("--max-apps", type=int, help="start work on at most this many apps in this run (default: all)")
    p.add_argument("--unattended", action="store_true", help="nobody can answer: take the safe default for every question")
    p = sub.add_parser("answer")
    p.add_argument("--root", default=".")
    p.add_argument("pairs", nargs="+", help="<question id>=<value>")
    p = sub.add_parser("apps")
    p.add_argument("--root", default=".")
    p.add_argument("--json", required=True, help='{"<repo>": [{"path": "...", "id": "...", "kind": "..."}]}')
    p = sub.add_parser("done")
    p.add_argument("--root", default=".")
    p.add_argument("--task", action="append")
    p.add_argument("--failed")
    p.add_argument("--error")
    p = sub.add_parser("next")
    p.add_argument("--root", default=".")
    p = sub.add_parser("targets")
    p.add_argument("--root", default=".")
    args = parser.parse_args()
    handlers = {"targets": cmd_targets, "start": cmd_start, "answer": cmd_answer, "apps": cmd_apps, "done": cmd_done, "next": cmd_next}
    try:
        handlers[args.cmd](args)
    except Stop as stop:
        print(json.dumps({"action": "stop", "say": str(stop)}, ensure_ascii=False))
    except RuntimeError as error:
        print(json.dumps({"action": "stop", "say": "pipeline error: %s" % error}, ensure_ascii=False))
        sys.exit(2)


if __name__ == "__main__":
    main()
