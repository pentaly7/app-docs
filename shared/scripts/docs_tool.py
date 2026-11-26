#!/usr/bin/env python3
"""Deterministic helpers for the app-docs plugin. Python 3.8+ stdlib only.

Subcommands (all print JSON to stdout):
  meta        HEAD sha, branch, dirty flag (ignoring docs/), date, git user
  detect      candidate app roots in a repo, with language and hints
  author      original author of a line range (oldest commit touching it)
  drift       which documented sections are stale since their commit
  validate    non-LLM checks of one app's docs against conventions.md
  sync-plan   Docmost page plan: prepared markdown, hashes, what changed
  sync-record record one synced Docmost page in state.json
  svg-theme   apply the light/dark diagram palette to every .drawio.svg
  migrate     bring existing docs up to the current conventions (idempotent)
  readme-plan what /app-docs:readme needs per app: guides, verified commit vs HEAD, owners, links
  facts-snapshot / facts-diff   facts a rewrite must keep (numbers, names) before vs after
  keep-snapshot / keep-restore  hand-written <!-- app-docs:keep --> blocks survive every rewrite
  humanize-plan  every User Guide paragraph and table string in scope for the humanizer, with hints
  facts-set   apply the humanizer's edits to the facts file's Indonesian text in one call
  briefs      one brief per important flow for the flow agents
  diagrams    lay out, export and check an app's diagrams in one call; PNGs only for flagged ones
  assemble    merge flow agents' fragments into the guides, facts and app state, then render
  readme      rewrite the READMEs from the Dev Guides and facts (no model)
  check-fragment  a flow agent's self-check of its fragment before it finishes
  usage-spend real token spend of a run, from Claude Code's transcripts
  stamp       per-section dirty flag and subtitle, and file contents so drift survives squash merges
  render      fill the tables and lists in both guides from docs/.docgen/facts/<app>.json
  owners      owners and escalation target for one app (CODEOWNERS, else git history)
  upgrade-plan  what a plugin upgrade would redo, with a rough token estimate
  skill-pin   record the version of an outside skill (humanizer, draw.io) and report changes
  clip        put a file (or its text) on the OS clipboard for sync

Exit codes: 0 ok, 1 validation failures found, 2 usage/environment error.
"""
import argparse
import base64
import datetime
import fnmatch
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import zlib
from pathlib import Path

TEMPLATE_VERSION = 4
# Bumped when only the operator-guide humanizer rules change: re-humanize, don't regenerate.
HUMANIZER_VERSION = 2
# Bumped when only diagram rules change: redraw diagrams, keep the text.
DIAGRAM_VERSION = 8
# Bumped when only the sequence-story rules change: re-read the code and rewrite the stories.
STORY_VERSION = 4

# Light colors used by diagrams-style.md §8 → their dark-palette counterparts (same section, dark column).
DARK_FILL = {
    "#333333": "#B0B0B0", "#DAE8FC": "#1F3A5F", "#E1D5E7": "#3B2A4F", "#FFF2CC": "#4A3F12",
    "#D5E8D4": "#1E4024", "#FFE6CC": "#4A3215", "#B0E3E6": "#0F3D40", "#F5F5F5": "#2B2B2B",
    "#A9DFBF": "#1B4D2E", "#F8CECC": "#5C2323", "#FFF9DB": "#3D3820", "#E8F5E9": "#1B3A24",
    "#FDECEA": "#4A2020", "#FFFFFF": "#1E1E1E", "#1E8449": "#4CAF6E", "#B85450": "#E57373",
    "#000000": "#B0B0B0",
    "#2F2F2F": "#5A5A5A", "#F0E2C8": "#3D3220", "#F2D7E9": "#4A2440", "#E2EFDA": "#263A1C", "#EEF3EE": "#2B332B",
}
DARK_STROKE = {
    "#333333": "#B0B0B0", "#6C8EBF": "#6C9BD2", "#9673A6": "#B39DDB", "#D6B656": "#E0C35A",
    "#82B366": "#7BC47F", "#D79B00": "#F0A040", "#0E8088": "#4FC3C9", "#666666": "#9E9E9E",
    "#1E8449": "#4CAF6E", "#B85450": "#E57373", "#000000": "#B0B0B0",
    "#2F2F2F": "#8A8A8A", "#A0844F": "#C9A86A", "#A65C8C": "#D58BBF", "#548235": "#8FC26A", "#7A8C7A": "#A3B5A3",
}
DARK_TEXT = {"#1A1A1A": "#E8E8E8", "#000000": "#E8E8E8", "#FFFFFF": "#F0F0F0"}
DARK_BACKGROUND = "#1E1E1E"
DOCS_DIR = "docs"

PRUNE_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "target", "out", ".next",
    ".nuxt", ".svelte-kit", "coverage", ".idea", ".vscode", "__pycache__",
    ".gradle", ".mvn", "bower_components", ".turbo", ".cache", DOCS_DIR,
}
MARKERS = {
    "go.mod": "go",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
    "composer.json": "php",
    "package.json": "js",
}
FRONTEND_DEPS = {"react", "vue", "@angular/core", "next", "nuxt", "svelte",
                 "@sveltejs/kit", "vite", "react-scripts", "solid-js", "preact"}
BACKEND_DEPS = {"express", "@nestjs/core", "fastify", "koa", "hapi", "@hapi/hapi",
                "restify", "socket.io", "amqplib", "kafkajs", "bull", "bullmq"}
CODE_EXTS = {
    "go", "java", "kt", "kts", "groovy", "gradle", "php", "js", "jsx", "ts", "tsx",
    "mjs", "cjs", "vue", "svelte", "py", "rb", "sql", "sh", "xml", "yml", "yaml",
    "json", "properties", "toml", "ini", "conf", "env", "proto", "graphql", "gql",
    "tf", "html", "twig", "css", "scss", "md", "mod", "sum", "lock",
}

ANCHOR_RE = re.compile(r'^<!--\s*docgen:section\s+id="([^"]+)"\s*-->\s*$')
HEADING_RE = re.compile(r"^#{2,6}\s+\S")
SUBTITLE_RE = re.compile(
    r"^> generated at `[0-9a-f]{7,40}`( \+ uncommitted changes)? on `[^`]+`, \d{4}-\d{2}-\d{2}, run by \S.*$"
)
OLD_SUBTITLE_RE = re.compile(
    r"^> `([0-9a-f]{7,40})`( \+ uncommitted changes)? · `([^`]+)` · (\d{4}-\d{2}-\d{2}) · verified by (\S.*)$"
)
CODE_REF_RE = re.compile(r"`([A-Za-z0-9_.@+/-]+\.([A-Za-z0-9]+)):(\d+)(?:-(\d+))?`")
LINKED_REF_RE = re.compile(r"\[`([A-Za-z0-9_.@+/-]+\.[A-Za-z0-9]+):(\d+)(?:-(\d+))?`\]\(([^)\s]+)\)")
FACT_UNIT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:ms|s|sec|seconds?|detik|min|minutes?|menit|h|hours?|jam|d|days?|hari|KB|MB|GB|%)(?![\w])", re.I)
FACT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:[._][A-Z0-9]+)+$")
STATUS_RE = re.compile(r"^[1-5]\d\d$")
# The two guides use different languages, so "5 menit" and "5 minutes" must compare equal.
UNIT_ALIASES = {"sec": "s", "second": "s", "seconds": "s", "detik": "s",
                "min": "min", "minute": "min", "minutes": "min", "menit": "min",
                "hour": "h", "hours": "h", "jam": "h", "day": "d", "days": "d", "hari": "d",
                "kb": "kb", "mb": "mb", "gb": "gb"}
SYMBOL_RE = re.compile(r"^([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)(?:\(.*\))?$")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+\.drawio\.svg)\)")
MERMAID_BLOCK_RE = re.compile(r"^```mermaid[ \t]*\n(.*?)^```", re.M | re.S)
PRONOUN_RE = re.compile(r"\b(Anda|kamu)\b", re.I)
SLANG_RE = re.compile(r"\b(nggak|ngga|gak|enggak|udah|aja|banget|bikin|kalo|gimana|nyimpen|ngecek|nandain)\b", re.I)
DASH_RE = re.compile(r"[\u2013\u2014]")
# Sections that must carry diagrams, with the minimum count (diagrams.md §1).
DIAGRAM_SECTIONS = {
    "dev": {"structure": 1, "startup": 1, "data-flow": 1},
    "op": {"how-it-works": 2, "data-flow": 1},
}
STORY_LINE_RE = re.compile(r"^\s*(\d+)\.\s")   # story items: "5. …", the number is the arrow number
DEV_ONLY_MARKS = ("**Unverified:**", "**Contradiction:**", "**Security finding:**")
REQUIRED_SECTIONS = {
    "dev": ["overview", "structure", "setup", "startup", "app-flow", "data-flow", "dev-notes", "glossary"],
    "op": ["setup", "how-it-works", "app-flow", "data-flow", "troubleshooting", "log-index", "alerts", "owners", "glossary"],
}
# Sections added by a template version. A repo that declined the upgrade isn't asked for them.
SECTIONS_SINCE = {"log-index": 3, "alerts": 3, "owners": 3}
# What it takes to bring docs from one template version to the next, without regenerating.
# A repo whose version has no step here gets a full regeneration.
TEMPLATE_STEPS = {
    2: {"to": 3, "action": "extend", "sections": {"op": ["log-index", "alerts", "owners"]}},
    3: {"to": 4, "action": "facts"},   # tables and lists move into docs/.docgen/facts/<app>.json and are rendered
}


def app_template(app_state, state):
    """The template an app's docs follow. Apps can differ: one with drift is converted before the rest."""
    return app_state.get("template_version") or state.get("template_version") or TEMPLATE_VERSION


def template_path(version):
    """The upgrade steps from `version` to the current template, or None when a full regeneration is needed."""
    steps = []
    while version != TEMPLATE_VERSION:
        step = TEMPLATE_STEPS.get(version)
        if step is None:
            return None
        steps.append(dict(step, **{"from": version}))
        version = step["to"]
    return steps
SECRET_PATTERNS = [
    ("aws access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("github token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("gitlab token", re.compile(r"glpat-[A-Za-z0-9_-]{20,}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("credential assignment", re.compile(
        r"(?i)(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)\s*[=:]\s*[\"']?([^\s\"'`<>{}$|]{6,})")),
    ("credential in URL", re.compile(r"://[^/\s:@<>`]+:([^@\s<>`/]+)@")),
]
PLACEHOLDER_SECRETS = {"password", "pass", "secret", "changeme", "example", "xxxxxx", "******", "redacted"}


# ---------------------------------------------------------------- git helpers

def git(repo, *args, check=True):
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), proc.stderr.strip()))
    return proc.stdout


def changed_paths_outside_docs(repo):
    """Uncommitted changes (tracked + untracked), ignoring the plugin's own docs/ output."""
    paths = []
    for line in git(repo, "status", "--porcelain", "--untracked-files=all").splitlines():
        path = line[3:].split(" -> ")[-1].strip('"')
        if not (path == DOCS_DIR or path.startswith(DOCS_DIR + "/")):
            paths.append(path)
    return paths


class FileAtCommit:
    """Cached line counts of files at a commit, or in the working tree when sha is None."""

    def __init__(self, repo):
        self.repo = repo
        self._cache = {}

    def lines(self, sha, path):
        if sha is None:
            full = Path(self.repo) / path
            return full.read_text(errors="replace").splitlines() if full.is_file() else None
        proc = subprocess.run(["git", "-C", str(self.repo), "show", "%s:%s" % (sha, path)], capture_output=True, text=True, errors="replace")
        return proc.stdout.splitlines() if proc.returncode == 0 else None

    def line_count(self, sha, path):
        key = (sha, path)
        if key not in self._cache:
            if sha is None:
                full = Path(self.repo) / path
                text = full.read_text(errors="replace") if full.is_file() else None
            else:
                proc = subprocess.run(["git", "-C", str(self.repo), "show", "%s:%s" % (sha, path)],
                                      capture_output=True, text=True, errors="replace")
                text = proc.stdout if proc.returncode == 0 else None
            self._cache[key] = None if text is None else len(text.splitlines())
        return self._cache[key]


def web_url(repo):
    """https://host/group/project for the 'origin' remote (SSH or HTTPS forms), or None."""
    url = git(repo, "remote", "get-url", "origin", check=False).strip()
    if not url:
        return None
    match = (re.match(r"^[\w.-]+@([^:/]+):(.+?)(?:\.git)?/?$", url) or
             re.match(r"^ssh://(?:[^@/]+@)?([^:/]+)(?::\d+)?/(.+?)(?:\.git)?/?$", url) or
             re.match(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", url))
    return "https://%s/%s" % (match.group(1), match.group(2)) if match else None


def is_pushed(repo, sha):
    return bool(git(repo, "branch", "-r", "--contains", sha, check=False).strip())


def permalink(base, sha, path, start, end=None):
    lines = "L%d" % start if not end or end == start else "L%d-%d" % (start, end)
    return "%s/-/blob/%s/%s#%s" % (base, sha, path, lines)


def emit(payload, code=0):
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.exit(code)


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


# ---------------------------------------------------------------- meta

def cmd_meta(args):
    repo = args.repo
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    emit({
        "sha": git(repo, "rev-parse", "HEAD").strip(),
        "short_sha": git(repo, "rev-parse", "--short=7", "HEAD").strip(),
        "branch": "detached" if branch == "HEAD" else branch,
        "dirty": bool(changed_paths_outside_docs(repo)),
        "dirty_files": changed_paths_outside_docs(repo)[:50],
        "windows_drive": bool(re.match(r"^/mnt/[a-z]/", str(Path(repo).resolve()))),
        "date": datetime.date.today().isoformat(),
        "user": git(repo, "config", "user.name", check=False).strip() or "unknown",
        "web_url": web_url(repo),
        "head_pushed": is_pushed(repo, "HEAD"),
        "template_version": TEMPLATE_VERSION,
        "humanizer_version": HUMANIZER_VERSION,
        "diagram_version": DIAGRAM_VERSION,
        "story_version": STORY_VERSION,
    })


# ---------------------------------------------------------------- detect

def _read(path, limit=200_000):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def _hints(directory, markers):
    hints = {}
    if "package.json" in markers:
        try:
            pkg = json.loads(_read(directory / "package.json"))
        except ValueError:
            pkg = {}
        deps = set(pkg.get("dependencies", {})) | set(pkg.get("devDependencies", {}))
        hints["name"] = pkg.get("name")
        hints["workspace_root"] = bool(pkg.get("workspaces"))
        hints["frontend_deps"] = sorted(deps & FRONTEND_DEPS)
        hints["backend_deps"] = sorted(deps & BACKEND_DEPS)
        hints["scripts"] = sorted(pkg.get("scripts", {}))
    if "go.mod" in markers:
        first = _read(directory / "go.mod", 2000).splitlines()
        hints["module"] = first[0].replace("module", "").strip() if first else None
        hints["main_packages"] = sorted({
            str(p.parent.relative_to(directory)) for p in _walk_files(directory, ".go", 3000)
            if re.search(r"^package main\b", _read(p, 4000), re.M)
        })[:20]
    if "composer.json" in markers:
        try:
            req = set(json.loads(_read(directory / "composer.json")).get("require", {}))
        except ValueError:
            req = set()
        hints["frameworks"] = sorted(r for r in req if r.startswith(("laravel/", "symfony/", "slim/", "codeigniter")))
        hints["has_artisan"] = (directory / "artisan").exists()
    if "pom.xml" in markers:
        pom = _read(directory / "pom.xml")
        hints["aggregator"] = "<packaging>pom</packaging>" in pom
        hints["spring_boot"] = "spring-boot" in pom
    for gradle in ("build.gradle", "build.gradle.kts"):
        if gradle in markers:
            text = _read(directory / gradle)
            hints["spring_boot"] = hints.get("spring_boot") or "spring-boot" in text or "org.springframework.boot" in text
            hints["application_plugin"] = "application" in text
    return hints


def _walk_files(root, suffix, limit):
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.endswith(suffix):
                yield Path(dirpath) / name
                count += 1
                if count >= limit:
                    return


def detect_apps(repo):
    repo = Path(repo).resolve()
    found = []
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = sorted(d for d in dirnames if d not in PRUNE_DIRS and not d.startswith("."))
        markers = sorted(m for m in MARKERS if m in filenames)
        if markers:
            directory = Path(dirpath)
            rel = directory.relative_to(repo).as_posix()
            found.append({
                "path": "." if rel == "." else rel,
                "languages": sorted({MARKERS[m] for m in markers}),
                "markers": markers,
                "hints": _hints(directory, markers),
            })
    paths = [f["path"] for f in found]
    for item in found:
        parents = [p for p in paths if p != item["path"] and (p == "." or item["path"].startswith(p + "/"))]
        item["nested_in"] = max(parents, key=len) if parents else None
    _assign_ids(found, repo.name)
    return found


def _kebab(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "app"


def _assign_ids(found, repo_name):
    base = [_kebab(repo_name if f["path"] == "." else f["path"].split("/")[-1]) for f in found]
    for item, short in zip(found, base):
        item["suggested_id"] = short if base.count(short) == 1 else _kebab(item["path"])


def cmd_detect(args):
    apps = detect_apps(args.repo)
    emit({"count": len(apps), "split_all": len(apps) > 10, "candidates": apps})


# ---------------------------------------------------------------- author

def cmd_author(args):
    proc = subprocess.run(
        ["git", "-C", args.repo, "log", "-L", "%d,%d:%s" % (args.start, args.end, args.file),
         "--format=DOCGEN%x09%H%x09%an%x09%ad", "--date=short"],
        capture_output=True, text=True, errors="replace")
    commits = [line.split("\t")[1:] for line in proc.stdout.splitlines() if line.startswith("DOCGEN\t")]
    if proc.returncode != 0 or not commits:
        emit({"name": None, "reason": (proc.stderr.strip() or "no commits touch these lines (uncommitted?)")})
    sha, name, date = commits[-1]
    emit({"name": name, "sha": sha, "short_sha": sha[:7], "date": date, "commits_touching": len(commits)})


# ---------------------------------------------------------------- drift

def _diff_since(repo, sha):
    """Map of path -> (status, new_path) for committed changes sha..HEAD, docs/ excluded."""
    out = {}
    for line in git(repo, "diff", "--name-status", "-M", sha, "HEAD").splitlines():
        parts = line.split("\t")
        status = parts[0][0]
        old, new = parts[1], parts[-1]
        if old.startswith(DOCS_DIR + "/"):
            continue
        out[old] = (status, new)
        if status == "R":
            out.setdefault(new, ("M", new))
    return out


def _min_template(repo, state):
    versions = []
    for app_id in state.get("apps", {}):
        app_file = Path(repo) / DOCS_DIR / ".docgen" / "apps" / ("%s.json" % app_id)
        versions.append(app_template(load_json(app_file) if app_file.exists() else {}, state))
    return min(versions) if versions else state.get("template_version")


def _blob_ids(repo, sha, paths):
    """{path: blob id} at a commit (None for a path that doesn't exist there)."""
    out = {p: None for p in paths}
    if not paths:
        return out
    listing = git(repo, "ls-tree", "-r", sha or "HEAD", "--", *paths, check=False)
    for line in listing.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and path in out:
            out[path] = parts[2]
    return out


DIRTY_MARK = " + uncommitted changes"


def _stamp(repo, app_state):
    """Per section: dirty only when one of its own files has uncommitted changes (not when anything in
    the tree does), the subtitle to match, and the blob ids of its files for drift."""
    working = set(changed_paths_outside_docs(repo))
    stamped, subtitle_fixes = 0, {}
    for key, section in app_state.get("sections", {}).items():
        dirty = any(p in working for p in section.get("files", []))
        subtitle_fixes[key] = dirty
        section["dirty"] = dirty
        sha = section.get("sha")
        if not sha or dirty or section.get("blobs_at") == sha:
            continue
        if not git(repo, "cat-file", "-t", sha, check=False).strip():
            continue
        section["blobs"] = _blob_ids(repo, sha, section.get("files", []))
        section["blobs_at"] = sha
        stamped += 1
    for kind, doc_key in (("dev", "dev"), ("op", "operator")):
        for path in _doc_files(Path(repo), app_state.get("docs", {}).get(doc_key, "")):
            doc = Doc(path, Path(repo))
            changed = False
            for line_index, sid in doc.anchors:
                want = subtitle_fixes.get("%s:%s" % (kind, sid))
                if want is None:
                    continue
                for j in range(line_index + 1, min(line_index + 4, len(doc.lines))):
                    line = doc.lines[j]
                    if line.startswith("> generated at `"):
                        new = line.replace(DIRTY_MARK, "") if not want else (
                            line if DIRTY_MARK in line else re.sub(r"(^> generated at `[0-9a-f]+`)", r"\1" + DIRTY_MARK, line))
                        if new != line:
                            doc.lines[j] = new
                            changed = True
                        break
            if changed:
                path.write_text("\n".join(doc.lines) + "\n", encoding="utf-8")
    return stamped


def cmd_stamp(args):
    """Record each section's file contents (git blob ids) at its commit. Drift compares these with HEAD,
    so a squash merge or rebase that drops the commit doesn't make every section look stale."""
    app_state = load_json(args.app_state)
    stamped = _stamp(args.repo, app_state)
    save_json(args.app_state, app_state)
    emit({"stamped": stamped})


def cmd_drift(args):
    repo = args.repo
    state_path = Path(repo) / DOCS_DIR / ".docgen" / "state.json"
    if not state_path.exists():
        emit({"error": "no state.json — run generate first"}, 2)
    state = load_json(state_path)
    working = set(changed_paths_outside_docs(repo))
    diff_cache = {}
    result = {
        "template_version_current": TEMPLATE_VERSION,
        "template_version_state": state.get("template_version"),
        "template_changed": template_path(_min_template(repo, state)) is None,
        "template_steps": template_path(_min_template(repo, state)) or [],
        "humanizer_version_current": HUMANIZER_VERSION,
        "humanizer_changed": state.get("humanizer_version") != HUMANIZER_VERSION,
        "diagram_version_current": DIAGRAM_VERSION,
        "diagram_changed": state.get("diagram_version") != DIAGRAM_VERSION,
        "story_version_current": STORY_VERSION,
        "story_changed": state.get("story_version", 1) != STORY_VERSION,
        "apps": {},
        "missing_app_state": [],
        "new_app_candidates": [],
    }
    for app_id, app in sorted(state.get("apps", {}).items()):
        app_file = Path(repo) / DOCS_DIR / ".docgen" / "apps" / ("%s.json" % app_id)
        if not app_file.exists():
            result["missing_app_state"].append(app_id)
            continue
        app_state = load_json(app_file)
        stale, renamed, deleted, added = {}, {}, set(), set()
        for key, section in sorted(app_state.get("sections", {}).items()):
            if section.get("status") == "removed":
                continue
            sha = section.get("sha", "")
            if sha not in diff_cache:
                try:
                    diff_cache[sha] = _diff_since(repo, sha)
                except RuntimeError:
                    diff_cache[sha] = None
            diff = diff_cache[sha]
            reasons = []
            if section.get("dirty"):
                reasons.append("generated from uncommitted changes")
            if diff is None and section.get("blobs"):
                head = _blob_ids(repo, "HEAD", list(section["blobs"]))
                for path, blob in sorted(section["blobs"].items()):
                    if head.get(path) != blob:
                        reasons.append("%s %s" % ("deleted" if head.get(path) is None else "modified", path))
                        if head.get(path) is None:
                            deleted.add(path)
                reasons += ["uncommitted change in %s" % p for p in section.get("files", []) if p in working]
            elif diff is None:
                reasons.append("commit %s not found (rebased or squashed)" % sha[:7])
            else:
                for path in section.get("files", []):
                    if path in diff:
                        status, new = diff[path]
                        reasons.append("%s %s" % ({"M": "modified", "D": "deleted", "R": "renamed", "A": "added"}.get(status, status), path))
                        if status == "R":
                            renamed[path] = new
                        if status == "D":
                            deleted.add(path)
                for path in section.get("files", []):
                    if path in working:
                        reasons.append("uncommitted change in %s" % path)
                root = app_state.get("root", ".").rstrip("/")
                for path, (status, new) in diff.items():
                    if status == "A" and (root == "." or new.startswith(root + "/")):
                        added.add(new)
            if reasons:
                stale[key] = sorted(set(reasons))
        result["apps"][app_id] = {
            "up_to_date": not stale,
            "stale_sections": stale,
            "renamed": renamed,
            "deleted": sorted(deleted),
            "added_files": sorted(added)[:200],
        }
    known_roots = {app.get("root") for app in state.get("apps", {}).values()}
    result["new_app_candidates"] = [c for c in detect_apps(repo) if c["path"] not in known_roots]
    emit(result)


# ---------------------------------------------------------------- validate

class Doc:
    def __init__(self, path, repo):
        self.path = Path(path)
        self.rel = self.path.relative_to(repo).as_posix()
        self.lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        self.anchors = []  # (line_index, section_id)
        for i, line in enumerate(self.lines):
            match = ANCHOR_RE.match(line.strip())
            if match:
                self.anchors.append((i, match.group(1)))

    def section_at(self, index):
        current = None
        for line_index, section_id in self.anchors:
            if line_index > index:
                break
            current = section_id
        return current

    def section_text(self, section_id):
        for pos, (line_index, sid) in enumerate(self.anchors):
            if sid == section_id:
                end = self.anchors[pos + 1][0] if pos + 1 < len(self.anchors) else len(self.lines)
                return "\n".join(self.lines[line_index:end])
        return None


NUMBER_WORDS = {"dua": 2, "tiga": 3, "empat": 4, "lima": 5, "enam": 6, "tujuh": 7, "delapan": 8, "sembilan": 9, "sepuluh": 10,
                "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
# "satu"/"one" are left out: they're mostly articles ("satu row", "one of"), not counts.
NUMBER_WORD_RE = re.compile(r"\b(%s)\b" % "|".join(NUMBER_WORDS), re.I)
LIST_MARKER_RE = re.compile(r"^\s*(?:\d+\.|[-*])\s+|^\s*\*\*(?:[A-Z]|\d+)\.\*\*\s*")
BARE_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")


def section_facts(text):
    """Facts a rewrite must not lose and two copies must agree on: backtick names (not code refs or
    links), numbers with units, and bare numbers such as retry counts, limits and status codes
    ("#3", "#502"). Number words count as their digits. Headings, subtitles, list numbers and arrow
    numbers are structure, not facts."""
    facts = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "<!--", "![")) or SUBTITLE_RE.match(stripped):
            continue
        line = LIST_MARKER_RE.sub("", LINKED_REF_RE.sub("", line))
        for span in re.findall(r"`([^`\n]+)`", line):
            if not CODE_REF_RE.match("`%s`" % span):
                facts.add(span.strip())
        prose = re.sub(r"`[^`\n]*`", " ", line)
        for number in FACT_UNIT_RE.findall(prose):
            value, unit = re.match(r"([\d.,]+)\s?(\S+)", number).groups()
            facts.add(value.replace(",", ".") + UNIT_ALIASES.get(unit.lower(), unit.lower()))
        prose = FACT_UNIT_RE.sub(" ", prose)
        for number in BARE_NUMBER_RE.findall(prose):
            facts.add("#" + number.replace(",", "."))
        for word in NUMBER_WORD_RE.findall(prose):
            facts.add("#%d" % NUMBER_WORDS[word.lower()])
    return facts


def _sections_of(docs):
    out = {}
    for doc in docs:
        for _, sid in doc.anchors:
            text = doc.section_text(sid)
            if text is not None:
                out[sid] = text
    return out


CODE_SKIP_DIRS = {".git", "node_modules", "vendor", "docs", "dist", "build", "target", ".idea", ".venv", "__pycache__"}


def _code_corpus(root):
    """All text under an app's folder as one string, for "does this literal exist" checks."""
    chunks = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in CODE_SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                if path.stat().st_size <= 1_000_000:
                    chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                pass
    return "\n".join(chunks)


def _first_column_spans(text):
    """The backtick text in the first cell of each markdown table row (header and rule rows skipped)."""
    spans = []
    for line in text.splitlines():
        cells = line.strip().strip("|").split("|")
        if not line.lstrip().startswith("|") or set(cells[0].strip()) <= set("-: "):
            continue
        found = re.match(r"^\s*`([^`]+)`", cells[0])
        if found:
            spans.append(found.group(1))
    return spans


def _doc_files(repo, target):
    path = Path(repo) / target
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.rglob("*.md"))
    return []


def _secret_values_from_env_files(repo):
    values = set()
    skip = ("example", "sample", "dist", "template", "defaults")
    for env in Path(repo).rglob(".env*"):
        if any(part in PRUNE_DIRS for part in env.parts) or any(s in env.name.lower() for s in skip) or not env.is_file():
            continue
        for line in _read(env).splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                value = line.split("=", 1)[1].strip().strip("\"'")
                if len(value) >= 8 and not value.isdigit() and value.lower() not in ("true", "false", "localhost"):
                    values.add(value)
    return values


def _is_code_ref(path, ext, repo):
    return "/" in path or ext.lower() in CODE_EXTS or (Path(repo) / path).exists()


def _diagrams_in(text):
    """(kind, source) for every diagram in a markdown fragment; kind is flowchart, sequence or other."""
    found = []
    for image in IMAGE_RE.findall(text):
        name = Path(image).name
        kind = "sequence" if ".seq." in name else "flowchart" if ".flow." in name else "state" if ".state." in name else "other"
        found.append((kind, image))
    for body in MERMAID_BLOCK_RE.findall(text):
        first = next((l.strip() for l in body.splitlines() if l.strip()), "")
        kind = ("sequence" if first.startswith("sequenceDiagram") else "flowchart" if first.startswith(("flowchart", "graph"))
                else "state" if first.startswith("stateDiagram") else "other")
        found.append((kind, body))
    return found


def _drawio_xml(svg_text):
    """Diagram XML embedded in a .drawio.svg (pages joined), and the page count; (None, 0) if not editable."""
    match = re.search(r'\scontent="([^"]*)"', svg_text)
    if not match:
        return None, 0
    pages = re.findall(r"<diagram\b[^>]*>(.*?)</diagram>", html.unescape(match.group(1)), re.S)
    xml = []
    for inner in (p.strip() for p in pages):
        if inner.startswith("<"):
            xml.append(inner)
            continue
        try:  # draw.io's compressed form: base64 of raw deflate of URL-encoded XML
            xml.append(urllib.parse.unquote(zlib.decompress(base64.b64decode(inner), -15).decode("utf-8")))
        except (ValueError, zlib.error, UnicodeDecodeError):
            xml.append("")
    return "\n".join(xml), len(pages)


def _drawio_problems(path):
    """(failures, warnings) for one .drawio.svg against diagrams.md §2, §8, §9."""
    xml, pages = _drawio_xml(_read(path, 20_000_000))
    if xml is None:
        return [("diagram-not-editable", "no embedded draw.io XML (export with -e)")], []
    failures, warnings = [], []
    if pages > 1:
        failures.append(("diagram-multi-page", "%d pages; only the first renders — split into files" % pages))
    fills = {c.upper() for c in re.findall(r"fillColor=(#[0-9A-Fa-f]{6})", xml)} - {"#FFFFFF"}
    if len(fills) < 2:
        failures.append(("diagram-no-color", "fewer than 2 fill colors"))
    if not re.search(r'value="[^"]*legend', xml, re.I):
        failures.append(("diagram-no-legend", "no Legend box"))
    if 'id="docgen-theme"' not in _read(path, 20_000_000):
        warnings.append("diagram theme not applied yet (docs_tool.py svg-theme)")
    return failures, warnings



def flow_section_problems(text, prefix, flow):
    """Diagram and story rules for one important flow's section (diagrams-flow.md §4–5). A sequence
    diagram and its story are required only for flows that call another system (`external`)."""
    sid = "app-flow/%s" % flow["id"]
    kinds = {kind for kind, _ in _diagrams_in(text)}
    needed = {"flowchart", "sequence"} if flow.get("external", True) else {"flowchart"}
    missing = needed - kinds
    if missing:
        return [("diagram-missing", "section '%s' has no %s" % (sid, " or ".join(sorted(missing))))]
    if prefix != "dev" or "sequence" not in kinds:
        return []
    # every arrow line of the story carries its code reference inline (diagrams-flow.md §5)
    seq_at = max(text.rfind(".seq."), text.rfind("sequenceDiagram"))
    arrow_lines = [l for l in text[seq_at:].splitlines() if STORY_LINE_RE.match(l)]
    bare = [STORY_LINE_RE.match(l).group(1) for l in arrow_lines if not CODE_REF_RE.search(l)]
    if not arrow_lines:
        return [("story-missing", "section '%s': no numbered arrow items under the sequence diagram" % sid)]
    if bare:
        return [("story-code-missing", "section '%s': arrow lines without an inline file:line reference: %s" % (sid, " ".join(bare)))]
    return []


def cmd_check_fragment(args):
    """A flow agent's self-check before it finishes: its fragment against the rules validate will apply
    after assembly (diagrams, stories, code references in range, no code in the User Guide)."""
    repo = Path(args.repo).resolve()
    frag = Path(args.fragment_dir)
    if not frag.is_absolute():
        frag = repo / frag
    app_state = load_json(args.app_state)
    flow = next((f for f in app_state.get("flows", []) if f["id"] == frag.name), {"id": frag.name})
    part = load_json(frag / "state.json") if (frag / "state.json").exists() else {}
    flow = dict(flow, **part.get("flow", {}))
    files = FileAtCommit(repo)
    problems = []
    for kind in ("dev", "op"):
        path = frag / ("%s.md" % kind)
        if not path.exists():
            if not (frag / ("story-%s.md" % kind)).exists():
                problems.append({"file": path.name, "rule": "fragment-missing", "message": "no %s.md" % kind})
            continue
        text = path.read_text(encoding="utf-8")
        for rule, message in flow_section_problems(text, kind, flow):
            problems.append({"file": path.name, "rule": rule, "message": message})
        section = part.get("sections", {}).get("%s:app-flow/%s" % (kind, frag.name), {})
        sha = section.get("sha") or "HEAD"
        for i, line in enumerate(text.splitlines(), start=1):
            for m in CODE_REF_RE.finditer(line):
                if not _is_code_ref(m.group(1), m.group(2), repo):
                    continue
                if kind == "op":
                    problems.append({"file": path.name, "line": i, "rule": "code-ref-in-user-guide", "message": m.group(0)})
                    continue
                start = int(m.group(3)); end = int(m.group(4) or start)
                count = files.line_count(sha, m.group(1))
                if count is None:
                    problems.append({"file": path.name, "line": i, "rule": "code-ref-file", "message": "%s not found" % m.group(1)})
                elif end > count or end < start:
                    problems.append({"file": path.name, "line": i, "rule": "code-ref-lines", "message": "%s: file has %d lines" % (m.group(0), count)})
        for image in IMAGE_RE.findall(text):
            target = repo / DOCS_DIR / app_state.get("app_id", "") / image
            if not image.startswith("http") and not target.exists():
                problems.append({"file": path.name, "rule": "image-missing", "message": image})
    emit({"ok": not problems, "problems": problems}, 1 if problems else 0)


def cmd_validate(args):
    repo = Path(args.repo).resolve()
    app_state = load_json(args.app_state)
    sections = app_state.get("sections", {})
    files = FileAtCommit(repo)
    failures, warnings = [], []
    checked_images = set()

    def fail(doc, line, rule, message):
        failures.append({"doc": doc, "line": line, "rule": rule, "message": message})

    docs = {kind: [Doc(p, repo) for p in _doc_files(repo, app_state.get("docs", {}).get(kind, ""))]
            for kind in ("dev", "operator")}
    env_secrets = _secret_values_from_env_files(repo)
    state_file = repo / DOCS_DIR / ".docgen" / "state.json"
    repo_template = app_template(app_state, load_json(state_file) if state_file.exists() else {})
    base_url = web_url(repo)
    if base_url is None:
        warnings.append("no 'origin' remote: code references can't be checked as GitLab permalinks")

    for kind, doc_list in docs.items():
        prefix = "dev" if kind == "dev" else "op"
        if not doc_list:
            fail(app_state.get("docs", {}).get(kind, "?"), 0, "doc-missing", "%s doc not found" % kind)
            continue
        all_ids = {sid for d in doc_list for _, sid in d.anchors}
        anchor_list = [sid for d in doc_list for _, sid in d.anchors]
        for dup in sorted({x for x in anchor_list if anchor_list.count(x) > 1}):
            fail(doc_list[0].rel, 0, "anchor-duplicate", "section '%s' appears %d times" % (dup, anchor_list.count(dup)))
        required_ids = [sid for sid in REQUIRED_SECTIONS[prefix] if SECTIONS_SINCE.get(sid, 0) <= repo_template]
        required_ids += ["state-machine"] if app_state.get("fsm") and app_state.get("state_machines") else []
        for required in required_ids:
            if required not in all_ids:
                fail(doc_list[0].rel, 0, "section-missing", "required section '%s' has no anchor" % required)
        full_text = "\n".join("\n".join(d.lines) for d in doc_list)
        for leftover in re.findall(r'<!--\s*docgen:flow id="([^"]+)"', full_text):
            fail(doc_list[0].rel, 0, "flow-not-assembled", "flow '%s' placeholder left: its fragment was never assembled" % leftover)

        for flow in app_state.get("flows", []):
            if flow.get("label") and flow["label"] not in full_text:
                fail(doc_list[0].rel, 0, "flow-missing", "flow '%s' (%s) not mentioned" % (flow["id"], flow["label"]))
            if flow.get("important") and flow.get("status", "active") == "active":
                sid = "app-flow/%s" % flow["id"]
                text = next((d.section_text(sid) for d in doc_list if d.section_text(sid) is not None), None)
                if text is None:
                    fail(doc_list[0].rel, 0, "flow-section-missing", "important flow '%s' has no section" % flow["id"])
                    continue
                for rule, message in flow_section_problems(text, prefix, flow):
                    fail(doc_list[0].rel, 0, rule, message)

        for machine in app_state.get("state_machines", []) if app_state.get("fsm") else []:
            sid = "state-machine/%s" % machine.get("id")
            text = next((d.section_text(sid) for d in doc_list if d.section_text(sid) is not None), None)
            if text is None:
                fail(doc_list[0].rel, 0, "fsm-section-missing", "state machine '%s' has no section" % machine.get("id"))
                continue
            if "state" not in {kind for kind, _ in _diagrams_in(text)}:
                fail(doc_list[0].rel, 0, "diagram-missing", "section '%s' has no state diagram" % sid)
            if prefix == "dev" and any(st.get("inferred") for st in machine.get("states", [])) and "**Unverified:**" not in text:
                fail(doc_list[0].rel, 0, "fsm-unverified", "'%s' has inferred state names but no Unverified mark" % sid)

        for sid, minimum in DIAGRAM_SECTIONS[prefix].items():
            text = next((d.section_text(sid) for d in doc_list if d.section_text(sid) is not None), None)
            if text is not None and len(_diagrams_in(text)) < minimum:
                fail(doc_list[0].rel, 0, "diagram-missing", "section '%s' needs %d diagram(s)" % (sid, minimum))

        for doc in doc_list:
            text = "\n".join(doc.lines)
            for block in MERMAID_BLOCK_RE.finditer(text):
                first = block.group(1).lstrip().split("\n", 1)[0]
                if first.startswith(("flowchart", "graph")) and "classDef" not in block.group(1):
                    fail(doc.rel, text.count("\n", 0, block.start()) + 1, "diagram-no-color", "Mermaid flowchart without classDef colors")
            for line_index, sid in doc.anchors:
                rest = [l for l in doc.lines[line_index + 1:line_index + 4] if l.strip()]
                if not rest or not HEADING_RE.match(rest[0]):
                    fail(doc.rel, line_index + 1, "anchor-heading", "anchor '%s' not followed by a ## heading" % sid)
                elif len(rest) < 2 or not SUBTITLE_RE.match(rest[1].strip()):
                    fail(doc.rel, line_index + 1, "subtitle", "section '%s' has no valid provenance subtitle" % sid)
            for i, line in enumerate(doc.lines, start=1):
                ranges = []
                for image in IMAGE_RE.findall(line):
                    target = (doc.path.parent / image).resolve()
                    if not target.is_file():
                        fail(doc.rel, i, "diagram-file", "diagram file not found: %s" % image)
                    elif target not in checked_images:
                        checked_images.add(target)
                        problems, notes = _drawio_problems(target)
                        for rule, message in problems:
                            fail(doc.rel, i, rule, "%s: %s" % (image, message))
                        warnings.extend("%s: %s" % (image, note) for note in notes)
                if kind == "operator" and not ANCHOR_RE.match(line.strip()) and not line.startswith(">"):
                    prose = re.sub(r"`[^`]*`", "", line)
                    for word in PRONOUN_RE.findall(prose):
                        warnings.append("%s:%d uses '%s' (operator guide addresses no one)" % (doc.rel, i, word))
                    for word in SLANG_RE.findall(prose):
                        warnings.append("%s:%d slang '%s' (semiformal, no slang)" % (doc.rel, i, word))
                    if DASH_RE.search(prose):
                        warnings.append("%s:%d em/en dash in operator prose" % (doc.rel, i))
                for match in CODE_REF_RE.finditer(line):
                    path, ext, start, end = match.group(1), match.group(2), int(match.group(3)), match.group(4)
                    if not _is_code_ref(path, ext, repo):
                        continue
                    if kind == "operator":
                        fail(doc.rel, i, "operator-code-ref", "operator guide must not cite file:line (%s)" % match.group(0))
                        continue
                    end = int(end) if end else start
                    section = sections.get("dev:%s" % doc.section_at(i - 1), {})
                    sha = None if section.get("dirty") else (section.get("sha") or "HEAD")
                    linked = next((m for m in LINKED_REF_RE.finditer(line) if m.start() <= match.start() < m.end()), None)
                    if base_url and linked is None:
                        fail(doc.rel, i, "code-ref-not-linked", "%s is not a GitLab permalink (conventions §5)" % match.group(0))
                    elif linked is not None and section.get("sha"):
                        expected = permalink(base_url or "", section["sha"], path, start, end if match.group(4) else None)
                        if base_url and linked.group(4) != expected:
                            warnings.append("%s:%d link for %s doesn't point at the section's commit (%s)" % (doc.rel, i, match.group(0), section["sha"][:7]))
                    count = files.line_count(sha, path)
                    where = "working tree" if sha is None else sha[:7]
                    if count is None:
                        fail(doc.rel, i, "code-ref-file", "%s not found at %s" % (path, where))
                    elif start < 1 or end < start or end > count:
                        fail(doc.rel, i, "code-ref-lines", "%s:%d-%d outside file (%d lines at %s)" % (path, start, end, count, where))
                    else:
                        ranges.append("\n".join((files.lines(sha, path) or [])[start - 1:end]))
                if kind == "dev" and ranges:
                    # a sentence that names functions should cite lines that contain at least one of them
                    symbols = []
                    for span in re.findall(r"`([^`\n]+)`", LINKED_REF_RE.sub("", line)):
                        m = SYMBOL_RE.match(span.strip())
                        if m and ("." in m.group(1) or "(" in span or re.search(r"[a-z][A-Z]", m.group(1))):
                            symbols.append(m.group(1).split(".")[-1])
                    if symbols and not any(sym in rng for sym in symbols for rng in ranges):
                        warnings.append("%s:%d none of %s appears in the cited lines" % (doc.rel, i, ", ".join("`%s`" % x for x in symbols[:3])))
                if kind == "operator" and any(mark in line for mark in DEV_ONLY_MARKS):
                    fail(doc.rel, i, "operator-mark", "dev-only mark in operator guide")
                for value in env_secrets:
                    if value in line:
                        fail(doc.rel, i, "secret-leak", "value from a .env file appears (%s…)" % value[:3])
                for name, pattern in SECRET_PATTERNS:
                    for found in pattern.finditer(line):
                        secret = found.group(found.lastindex) if found.lastindex else found.group(0)
                        if secret.lower().strip("*") in PLACEHOLDER_SECRETS or secret.startswith(("<", "$", "{", "%")):
                            continue
                        fail(doc.rel, i, "secret-pattern", "possible %s (%s…)" % (name, secret[:3]))

    for machine in app_state.get("state_machines", []) if app_state.get("fsm") else []:
        values = {str(st.get("value")) for st in machine.get("states", [])}
        transitions = machine.get("transitions", [])
        if len(values) < 3 or len(transitions) < 3:
            fail(args.app_state, 0, "fsm-threshold", "'%s' has %d states / %d transitions (needs 3 / 3)" % (machine.get("id"), len(values), len(transitions)))
        for t in transitions:
            if str(t.get("from")) not in values or str(t.get("to")) not in values:
                fail(args.app_state, 0, "fsm-transition", "'%s' transition %s → %s uses an unknown state" % (machine.get("id"), t.get("from"), t.get("to")))

    # rendered tables and lists (template 4): present, and identical to what the facts file renders
    if repo_template >= 4:
        import docs_render
        rendered = docs_render.render_app(repo, app_state, check=True)
        for item in rendered["changed"]:
            fail(item.split(":")[0], 0, "render-stale", "%s differs from the facts file: run docs_tool.py render (don't edit rendered blocks by hand)" % item)
        for item in rendered["missing_blocks"]:
            fail(args.app_state, 0, "render-missing", "rendered block missing: %s" % item)
        warnings.extend("unknown rendered block %s" % b for b in rendered["unknown_blocks"])

    # log messages and metric names in the User Guide must exist in the app's code (an operator greps for them)
    op_secs = _sections_of(docs["operator"])
    corpus = None
    for sid, rule, fatal in (("log-index", "log-message-unknown", True), ("alerts", "metric-unknown", False)):
        if sid not in op_secs:
            continue
        if corpus is None:
            corpus = _code_corpus(repo / app_state.get("root", "."))
        for cell in _first_column_spans(op_secs[sid]):
            fragments = [f.strip() for f in re.split(r"<[^>]*>", cell) if len(f.strip()) >= 4]
            missing = [f for f in fragments if f not in corpus]
            if fragments and missing:
                message = "'%s' lists `%s`, but `%s` isn't in the app's code" % (sid, cell, missing[0])
                if fatal:
                    fail(docs["operator"][0].rel, 0, rule, message)
                else:
                    warnings.append(message + " (fine if the name is built at runtime)")

    if base_url:
        unpushed = sorted({sec["sha"] for key, sec in sections.items() if key.startswith("dev:") and sec.get("sha")
                           and not is_pushed(repo, sec["sha"])})
        for sha in unpushed:
            warnings.append("commit %s isn't on any remote branch: its code links 404 until it is pushed" % sha[:7])

    # the same section in both guides must not disagree on numbers, keys or status codes
    # A User Guide fact must exist somewhere in the Dev Guide or the facts file, not necessarily in the
    # same section (the guides arrange things differently). One warning per section, with a count.
    dev_sections, op_sections = _sections_of(docs["dev"]), _sections_of(docs["operator"])
    known = set()
    for text in dev_sections.values():
        known |= section_facts(text)
    facts_file = repo / DOCS_DIR / ".docgen" / "facts" / ("%s.json" % app_state.get("app_id", ""))
    if facts_file.exists():
        raw = facts_file.read_text(encoding="utf-8")
        known |= section_facts(raw)
        known |= set(re.findall(r'"(?:key|name|message|symptom)":\s*"([^"]+)"', raw))
    for sid in sorted(op_sections):
        odd = sorted(f for f in section_facts(op_sections[sid])
                     if (FACT_UNIT_RE.fullmatch(f) or FACT_KEY_RE.match(f) or STATUS_RE.match(f.lstrip("#")))
                     and f not in known and f.lstrip("#") not in {k.lstrip("#") for k in known})
        if odd:
            warnings.append("fact-mismatch in '%s': %d fact(s) only in the User Guide: %s" % (sid, len(odd), ", ".join("`%s`" % f for f in odd[:5])))

    ids = [f["id"] for f in app_state.get("flows", [])]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        fail(args.app_state, 0, "flow-id-duplicate", "duplicate flow ids: %s" % ", ".join(duplicates))
    if not app_state.get("flows"):
        warnings.append("no flows recorded in app state")

    payload = {"ok": not failures, "failures": failures, "warnings": warnings,
               "stats": {"flows": len(ids), "important": sum(1 for f in app_state.get("flows", []) if f.get("important")),
                         "sections": len(sections)}}
    emit(payload, 0 if not failures else 1)


# ---------------------------------------------------------------- facts

def _app_sections(repo, app_state):
    docs = {kind: [Doc(p, repo) for p in _doc_files(repo, app_state.get("docs", {}).get(kind, ""))] for kind in ("dev", "operator")}
    return {"dev": _sections_of(docs["dev"]), "op": _sections_of(docs["operator"])}


TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{3,}")


def _cells(text):
    """Every table cell and list item, reduced to its words, for a cell-by-cell comparison."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and not TABLE_SEP_RE.match(stripped):
            out += [c.strip() for c in stripped.strip("|").split("|")]
        elif re.match(r"^(?:[-*]|\d+\.)\s", stripped):
            out.append(LIST_MARKER_RE.sub("", stripped))
    clean = []
    for cell in out:
        cell = re.sub(r"\]\([^)]*\)", "]", cell)
        words = re.findall(r"[\w<>@./:-]{2,}", cell.replace("`", " ").lower())
        if words and cell not in ("-",):
            clean.append(words)
    return clean


def cmd_facts_snapshot(args):
    repo = Path(args.repo).resolve()
    sections = _app_sections(repo, load_json(args.app_state))
    snap = {kind: {sid: sorted(section_facts(text)) for sid, text in secs.items()} for kind, secs in sections.items()}
    if args.cells:
        snap["cells"] = {kind: [w for text in secs.values() for w in _cells(text)] for kind, secs in sections.items()}
    save_json(args.out, snap)
    emit({"ok": True, "sections": sum(len(v) for v in snap.values())})


def cmd_facts_diff(args):
    """Facts lost or introduced since a snapshot. With --strict (after the humanizer) any change fails."""
    repo = Path(args.repo).resolve()
    before = load_json(args.before)
    now = _app_sections(repo, load_json(args.app_state))
    changes = []
    if args.cells and "cells" in before:
        # every word of every old cell must still be in the same guide (rendering may reorder or join cells)
        for kind in ("dev", "op"):
            words = set(" ".join(now[kind].values()).replace("`", " ").lower().split())
            words |= {w for cell in _cells("\n".join(now[kind].values())) for w in cell}
            for cell in before["cells"].get(kind, []):
                missing = [w for w in cell if w not in words]
                if len(missing) > len(cell) // 5:
                    changes.append({"doc": kind, "section": "(table or list)", "lost": [" ".join(cell)], "added": [], "missing_words": missing})
    for kind in ("dev", "op"):
        if args.only and kind != args.only:
            continue
        for sid, old in before.get(kind, {}).items():
            new = section_facts(now[kind].get(sid, ""))
            lost, added = sorted(set(old) - new), sorted(new - set(old))
            if lost or added:
                changes.append({"doc": kind, "section": sid, "lost": lost, "added": added})
    emit({"ok": not changes, "changes": changes}, 1 if (changes and args.strict) else 0)


# ---------------------------------------------------------------- keep blocks

KEEP_START_RE = re.compile(r"^<!--\s*app-docs:keep\s*-->\s*$")
KEEP_END_RE = re.compile(r"^<!--\s*/app-docs:keep\s*-->\s*$")


def _keep_blocks(lines):
    """[(start, end)] line ranges of <!-- app-docs:keep --> … <!-- /app-docs:keep --> blocks, markers included."""
    out, start = [], None
    for i, line in enumerate(lines):
        if KEEP_START_RE.match(line.strip()):
            start = i
        elif KEEP_END_RE.match(line.strip()) and start is not None:
            out.append((start, i))
            start = None
    return out


def cmd_keep_snapshot(args):
    """Save every hand-written keep block per section, before any agent touches the app."""
    repo = Path(args.repo).resolve()
    app_state = load_json(args.app_state)
    snap = {}
    for kind, doc_key in (("dev", "dev"), ("op", "operator")):
        for path in _doc_files(repo, app_state.get("docs", {}).get(doc_key, "")):
            doc = Doc(path, repo)
            for start, end in _keep_blocks(doc.lines):
                snap.setdefault(kind, {}).setdefault(doc.section_at(start) or "", []).append("\n".join(doc.lines[start:end + 1]))
    save_json(args.out, snap)
    emit({"blocks": sum(len(b) for k in snap.values() for b in k.values())})


def cmd_keep_restore(args):
    """Put back any keep block an agent dropped, at the end of its section. Deterministic, so a rewrite
    can never lose what a person filled in."""
    repo = Path(args.repo).resolve()
    app_state = load_json(args.app_state)
    snap = load_json(args.before) if Path(args.before).exists() else {}
    restored = []
    for kind, doc_key in (("dev", "dev"), ("op", "operator")):
        for sid, blocks in snap.get(kind, {}).items():
            for path in _doc_files(repo, app_state.get("docs", {}).get(doc_key, "")):
                doc = Doc(path, repo)
                text = doc.section_text(sid) if sid else "\n".join(doc.lines)
                if text is None:
                    continue
                missing = [b for b in blocks if b not in text]
                if missing:
                    pos = next((i for i, (line_index, s_id) in enumerate(doc.anchors) if s_id == sid), None)
                    end = doc.anchors[pos + 1][0] if pos is not None and pos + 1 < len(doc.anchors) else len(doc.lines)
                    lines = doc.lines[:end] + [""] + "\n\n".join(missing).split("\n") + [""] + doc.lines[end:]
                    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    restored += ["%s:%s" % (kind, sid)] * len(missing)
                break
    emit({"restored": restored})


# ---------------------------------------------------------------- humanize plan

# Tells the humanizer fixes (humanizer.md §5), as cheap regexes. They pick paragraphs; the skill does the edit.
TELL_RES = [
    ("stiff connector", re.compile(r"(?:^|[.!?]\s+)(Selain itu|Adapun|Dengan demikian|Oleh karena itu|Oleh sebab itu|Di samping itu|Lebih lanjut|Sementara itu),", re.I)),
    ("significance inflation", re.compile(r"\b(memainkan peran (penting|krusial)|sangat (krusial|penting)|peran vital)\b", re.I)),
    ("throat-clearing", re.compile(r"\b(Penting untuk dicatat|Perlu diketahui|Berikut (adalah|ini)|Perlu dicatat)\b", re.I)),
    ("officialese", re.compile(r"\b(dalam rangka|guna|yang bersangkutan|terkait dengan hal tersebut)\b", re.I)),
    ("light verb", re.compile(r"\b(melakukan|mengadakan) (pengecekan|pemeriksaan|penyimpanan|pengiriman|pemanggilan|pembaruan|validasi)\b", re.I)),
    ("relative-pronoun calque", re.compile(r"\b(yang mana|di mana)\b(?![^.]*\?)", re.I)),
    ("merupakan", re.compile(r"\bmerupakan\b", re.I)),
    ("not only … but also", re.compile(r"\bTidak hanya\b.*\btetapi juga\b", re.I)),
    ("empty closing", re.compile(r"\bSemoga (bermanfaat|membantu)\b", re.I)),
]
PROSE_SKIP_RE = re.compile(r"^(#|>|<!--|!\[|\||```)")


def _prose_paragraphs(doc, section_ids):
    """Prose paragraphs (list items count as one each) in the given sections, skipping headings,
    subtitles, marks, tables, code, images and rendered blocks: those must not change."""
    out, current, in_fence, in_render = [], [], False, False
    section_ids = set(section_ids) if section_ids else None

    def close(end):
        if current:
            # text is the paragraph exactly as in the file, so the humanizer can Edit it in place
            start, text = current[0][0], "\n".join(t for _, t in current)
            sid = doc.section_at(start)
            if section_ids is None or sid in section_ids:
                out.append({"doc": doc.rel, "section": sid, "start": start + 1, "end": end, "text": text})
            current.clear()

    for i, line in enumerate(doc.lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            close(i)
            continue
        if docs_render_marker(stripped) == "start" or KEEP_START_RE.match(stripped):
            in_render = True
        if in_fence or in_render or not stripped or PROSE_SKIP_RE.match(stripped):
            close(i)
            if docs_render_marker(stripped) == "end" or KEEP_END_RE.match(stripped):
                in_render = False
            continue
        if re.match(r"^(\d+\.|[-*])\s", stripped) or re.match(r"^\*\*[A-Z]\.", stripped):
            close(i)
        current.append((i, line))
    close(len(doc.lines))
    return out


def docs_render_marker(stripped):
    if re.match(r'^<!--\s*docgen:render\s', stripped):
        return "start"
    if re.match(r"^<!--\s*/docgen:render\s*-->", stripped):
        return "end"
    return None


# Which facts fields each User Guide block shows (Indonesian `id` text only; `manual` is people's text).
BLOCK_FACT_FIELDS = {
    "config": [("config", ["meaning"])],
    "config-effects": [("config", ["if_changed", "if_wrong"])],
    "storage": [("storage", ["data", "retention"])],
    "common-errors": [("common_errors", ["symptom", "meaning", "check"])],
    "log-index": [("logs", ["when", "meaning"])],
    "metrics": [("metrics", ["meaning"])],
    "alerts": [("alerts", ["when", "first_step"])],
}


def _table_strings(facts, block_id):
    """[(path, text)] of the Indonesian facts strings a User Guide block renders. Paths look like
    `config[2].meaning.id` or `flows.create.purpose.id`."""
    out = []
    name, _, flow = block_id.partition(":")
    for key, fields in BLOCK_FACT_FIELDS.get(block_id, []):
        for i, item in enumerate(facts.get(key, [])):
            for field in fields:
                if isinstance(item.get(field), dict) and item[field].get("id"):
                    out.append(("%s[%d].%s.id" % (key, i, field), item[field]["id"]))
    if block_id == "flow-index":
        for fid, item in sorted(facts.get("flows", {}).items()):
            for field in ("purpose", "check"):
                if isinstance(item.get(field), dict) and item[field].get("id"):
                    out.append(("flows.%s.%s.id" % (fid, field), item[field]["id"]))
    if block_id == "glossary":
        out += [("glossary[%d].id" % i, g["id"]) for i, g in enumerate(facts.get("glossary", [])) if g.get("id")]
    if name == "if-failed" and flow:
        for i, e in enumerate(facts.get("flow_details", {}).get(flow, {}).get("errors", [])):
            for field in ("when", "cause", "check"):
                if isinstance(e.get(field), dict) and e[field].get("id"):
                    out.append(("flow_details.%s.errors[%d].%s.id" % (flow, i, field), e[field]["id"]))
    return out


_PATH_PART_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def cmd_facts_set(args):
    """Apply a batch of text edits to the facts file in one call: a JSON list of {facts_path, text}, as
    the humanizer writes them. Only existing Indonesian `id` strings can change; `manual` never."""
    import docs_render
    repo = Path(args.repo).resolve()
    app_state = load_json(args.app_state)
    path = docs_render.facts_path(repo, app_state["app_id"])
    facts = load_json(path)
    applied, refused = 0, []
    for edit in load_json(args.edits):
        parts = [m.group(1) if m.group(1) is not None else int(m.group(2)) for m in _PATH_PART_RE.finditer(edit["facts_path"])]
        if not parts or parts[0] == "manual" or parts[-1] != "id":
            refused.append({"facts_path": edit["facts_path"], "why": "only Indonesian id text outside manual can change"})
            continue
        node = facts
        try:
            for part in parts[:-1]:
                node = node[part]
            if not isinstance(node.get("id"), str):
                raise KeyError("id")
        except (KeyError, IndexError, TypeError, AttributeError):
            refused.append({"facts_path": edit["facts_path"], "why": "no such field"})
            continue
        node["id"] = edit["text"]
        applied += 1
    save_json(path, facts)
    emit({"applied": applied, "refused": refused}, 1 if refused else 0)


def cmd_humanize_plan(args):
    """Everything the humanizer should polish in the User Guide sections in scope (default: all):
    every prose paragraph, and the Indonesian facts text its tables and lists are rendered from.
    Each paragraph lists the AI tells found in it, as hints. Keep blocks and `manual` facts are
    people's text and never included."""
    import docs_render
    repo = Path(args.repo).resolve()
    app_state = load_json(args.app_state)
    target = app_state.get("docs", {}).get("operator", "")
    scope = [s.split(":", 1)[1] for s in args.scope.split(",")] if args.scope else None
    facts = docs_render.load_facts(repo, app_state.get("app_id", ""))
    paragraphs, strings, seen = [], [], set()
    for path in _doc_files(repo, target):
        doc = Doc(path, repo)
        for para in _prose_paragraphs(doc, scope):
            prose = re.sub(r"`[^`]*`", "", " ".join(para["text"].split()))
            hints = [name for name, rx in TELL_RES if rx.search(prose)]
            hints += ["pronoun"] if PRONOUN_RE.search(prose) else []
            hints += ["slang"] if SLANG_RE.search(prose) else []
            hints += ["dash"] if DASH_RE.search(prose) else []
            paragraphs.append(dict(para, hints=hints))
        for i, line in enumerate(doc.lines):
            m = re.match(r'^<!--\s*docgen:render\s+id="([^"]+)"', line.strip())
            if m and (scope is None or doc.section_at(i) in scope):
                for fpath, text in _table_strings(facts, m.group(1)):
                    if fpath not in seen:
                        seen.add(fpath)
                        strings.append({"facts_path": fpath, "text": text, "block": m.group(1)})
    guide_notes = []
    metrik = Path(args.skill).expanduser() / "scripts" / "metrik.py" if args.skill and args.skill != "none" else None
    if metrik is not None and metrik.is_file():
        # sentence-length statistics only mean something for a whole guide: one note each, for the report
        for path in _doc_files(repo, target):
            proc = subprocess.run([sys.executable, str(metrik), str(path), "--preset", "semiformal"],
                                  capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
            guide_notes += ["%s: %s" % (Path(path).name, l.strip()) for l in proc.stdout.splitlines()
                            if proc.returncode == 0 and "PERIKSA" in l]
    plan = _work(repo, "humanize-%s-plan.json" % app_state.get("app_id", "app"))
    save_json(plan, {"paragraphs": paragraphs, "facts_strings": strings, "guide_notes": guide_notes})
    emit({"plan": plan.relative_to(repo).as_posix(), "paragraphs": len(paragraphs), "facts_strings": len(strings),
          "with_hints": sum(1 for p in paragraphs if p["hints"]), "guide_notes": guide_notes})


# ---------------------------------------------------------------- per-flow work: briefs, diagrams, assemble

def _work(repo, *parts):
    return Path(repo) / DOCS_DIR / ".docgen" / ".work" / Path(*parts)


def _flow_numbering(app_state):
    """Heading numbers and split-mode file names for important flows, in index order."""
    out, n = {}, 0
    for flow in app_state.get("flows", []):
        # removed flows keep their section (with a Removed mark), so they keep their number too
        if flow.get("important"):
            n += 1
            out[flow["id"]] = {"dev": "5.%d" % n, "op": "3.%d" % n,
                               "file": "05-app-flow/%02d-%s.md" % (n, flow["id"]), "op_file": "03-app-flow/%02d-%s.md" % (n, flow["id"])}
    return out


def cmd_briefs(args):
    """One brief per flow group (the app agent groups flows that share most of their code), so one agent
    reads a shared core once. Derived from the app state and facts; the orchestrator never writes them."""
    import docs_render
    repo = Path(args.repo).resolve()
    app_state = load_json(args.app_state)
    app_id = app_state["app_id"]
    numbering = _flow_numbering(app_state)
    wanted = set(args.flows.split(",")) if args.flows else set(numbering)
    facts = docs_render.load_facts(repo, app_id)
    terms = sorted(g.get("term", "") for g in facts.get("glossary", []))
    owned = {sub: f["id"] for f in app_state.get("flows", []) for sub in f.get("subflows_owned", [])}
    out_dir = _work(repo, "briefs", app_id)
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    groups = {}
    for flow in app_state.get("flows", []):
        if flow["id"] in wanted and flow["id"] in numbering and flow.get("status", "active") == "active":
            groups.setdefault(flow.get("group") or "all", []).append(flow)
    written = []
    for group, flows in groups.items():
        brief = {"app_id": app_id, "group": group, "split": bool(app_state.get("split")), "terms": terms,
                 "spec_dir": _work(repo, "specs", app_id).relative_to(repo).as_posix(),
                 "flows": [{"flow": f, "numbers": numbering[f["id"]],
                            "subflows_owned": f.get("subflows_owned", []),
                            "subflows_used": {sub: owned.get(sub) for sub in f.get("subflows_used", [])},
                            "fragment_dir": _work(repo, "fragments", app_id, f["id"]).relative_to(repo).as_posix(),
                            "existing": {kind: "%s:app-flow/%s" % (kind, f["id"]) in app_state.get("sections", {}) for kind in ("dev", "op")}}
                           for f in flows]}
        path = out_dir / ("%s.json" % group)
        save_json(path, brief)
        written.append({"brief": path.relative_to(repo).as_posix(), "flows": [f["id"] for f in flows]})
    emit({"briefs": written})


def _drawio_bin():
    for candidate in ("drawio", "draw.io", "/Applications/draw.io.app/Contents/MacOS/draw.io",
                      "/mnt/c/Program Files/draw.io/draw.io.exe", "/mnt/c/Program Files (x86)/draw.io/draw.io.exe"):
        if shutil.which(candidate) or Path(candidate).is_file():
            return shutil.which(candidate) or candidate
    return None


def cmd_diagrams(args):
    """Lay out, export and check every diagram spec of an app (or those starting with --only) in one call.
    Exports a PNG only for flagged diagrams, so an agent looks at those and nothing else."""
    repo = Path(args.repo).resolve()
    specs = sorted(_work(repo, "specs", args.app).glob("*.json"))
    if args.only:
        prefixes = tuple(args.only.split(","))
        specs = [p for p in specs if p.stem.startswith(prefixes)]
    layout = Path(__file__).resolve().parent / "diagram_layout.py"
    drawio = args.drawio or _drawio_bin()
    if drawio and not (shutil.which(drawio) or Path(drawio).is_file()):
        drawio = None
    out_dir = repo / DOCS_DIR / args.app / "diagrams"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    windows_exe = bool(drawio) and str(drawio).lower().endswith(".exe") and shutil.which("wslpath")

    def native(path):
        # the Windows draw.io app under WSL needs Windows paths
        if not windows_exe:
            return str(path)
        return subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True).stdout.strip()
    for spec in specs:
        name = spec.stem                       # create-payment.flow → create-payment.flow.drawio.svg
        source = _work(repo, "drawio", args.app, name + ".drawio")
        source.parent.mkdir(parents=True, exist_ok=True)
        preview = source.with_suffix(".preview.svg")
        proc = subprocess.run([sys.executable, str(layout), str(spec), "-o", str(source), "--preview", str(preview)],
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)
        entry = {"name": name}
        try:
            report = json.loads(proc.stdout)
        except ValueError:
            report = {"ok": False}
        if proc.returncode != 0 or not report.get("ok"):
            entry.update(ok=False, error=(proc.stderr or proc.stdout).strip()[-400:])
            results.append(entry)
            continue
        entry.update(label_overlaps=report.get("label_overlaps", 0), long_labels=report.get("long_labels", []))
        flagged = bool(entry["label_overlaps"] or entry["long_labels"])
        if drawio:
            svg = out_dir / (name + ".drawio.svg")
            try:
                export = subprocess.run([drawio, "-x", "-f", "svg", "-e", "-o", native(svg), native(source)],
                                        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
                message = (export.stderr or export.stdout).strip()[-300:]
                exported = export.returncode == 0 and svg.exists()
            except (OSError, subprocess.TimeoutExpired) as error:
                message, exported = str(error), False
            entry["svg"] = svg.relative_to(repo).as_posix() if exported else None
            if not exported:
                entry["error"] = "draw.io export failed: %s" % message
                flagged = True
            if flagged:
                png = _work(repo, "png", args.app, name + ".png")
                png.parent.mkdir(parents=True, exist_ok=True)
                try:
                    subprocess.run([drawio, "-x", "-f", "png", "-o", native(png), native(source)],
                                   capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                entry["png"] = png.relative_to(repo).as_posix() if png.exists() else None
        else:
            entry["error"] = "draw.io CLI not found"
            flagged = True
        entry["ok"] = not flagged
        if flagged and not entry.get("png") and preview.exists():
            entry["preview"] = preview.relative_to(repo).as_posix()   # rough layout picture when no PNG could be made
        results.append(entry)
    emit({"diagrams": len(results), "flagged": [r for r in results if not r["ok"]],
          "exported": sum(1 for r in results if r.get("svg"))})


def _rewrite_image_paths(text, target_file, app_dir):
    """Fragments embed diagrams as `diagrams/<file>` (single-mode paths); fix them for the file they land in."""
    rel = os.path.relpath(app_dir / "diagrams", target_file.parent).replace(os.sep, "/")
    return text.replace("](diagrams/", "](%s/" % rel) if rel != "diagrams" else text


def _place_section(doc_path, section_id, fragment):
    """Put a flow section into a single-mode guide: replace it if its anchor exists, else fill its
    docgen:flow placeholder, else append it after the last app-flow section."""
    lines = doc_path.read_text(encoding="utf-8").split("\n")
    frag = fragment.rstrip("\n").split("\n")
    anchors = [(i, m.group(1)) for i, l in enumerate(lines) for m in [ANCHOR_RE.match(l.strip())] if m]
    for pos, (i, sid) in enumerate(anchors):
        if sid == section_id:
            end = anchors[pos + 1][0] if pos + 1 < len(anchors) else len(lines)
            new = lines[:i] + frag + [""] + lines[end:]
            break
    else:
        placeholder = next((i for i, l in enumerate(lines) if l.strip().startswith('<!-- docgen:flow id="%s"' % section_id.split("/", 1)[1])), None)
        if placeholder is not None:
            new = lines[:placeholder] + frag + lines[placeholder + 1:]
        else:
            after = [i for i, sid in anchors if sid == "app-flow" or sid.startswith("app-flow/")]
            if not after:
                raise ValueError("no app-flow section in %s" % doc_path)
            last = max(after)
            nxt = next((i for i, _ in anchors if i > last), len(lines))
            new = lines[:nxt] + frag + [""] + lines[nxt:]
    doc_path.write_text("\n".join(new), encoding="utf-8")


STORY_START_RE = re.compile(r"^\*\*A\.\s")
STORY_END_RE = re.compile(r"^(\*\*Tanda berhasil|<!--\s*docgen:render|<!--\s*docgen:section|<!--\s*app-docs:keep)")


def _replace_story(target, split_file, flow_id, story):
    """Swap only the sequence story of one flow section (from its "**A." heading to the next rendered
    block, "Tanda berhasil" or section), so a story-only rewrite doesn't re-send the whole section."""
    if target.is_dir():
        path = target / split_file if split_file else None
        candidates = [path] if path and path.exists() else list(target.rglob("[0-9][0-9]-%s.md" % flow_id))
    else:
        candidates = [target]
    for path in candidates:
        lines = path.read_text(encoding="utf-8").split("\n")
        anchor = next((i for i, l in enumerate(lines) if l.strip() == '<!-- docgen:section id="app-flow/%s" -->' % flow_id), None)
        if anchor is None:
            continue
        end_of_section = next((i for i in range(anchor + 1, len(lines)) if ANCHOR_RE.match(lines[i].strip())), len(lines))
        start = next((i for i in range(anchor, end_of_section) if STORY_START_RE.match(lines[i])), None)
        if start is None:
            raise ValueError("no story (a \"**A.\" heading) in app-flow/%s" % flow_id)
        end = next((i for i in range(start + 1, end_of_section) if STORY_END_RE.match(lines[i].strip())), end_of_section)
        lines[start:end] = story.rstrip("\n").split("\n") + [""]
        path.write_text("\n".join(lines), encoding="utf-8")
        return
    raise ValueError("app-flow/%s not found for its story" % flow_id)


FLOW_HEADING_RE = re.compile(r"^(###\s+)\d+\.\d+(\s)")


def _renumber_flows(repo, app_state):
    """Give every flow section the heading number (and in split mode the file name) of its place in
    the index. Inserting or removing a flow shifts the others; this fixes them without a model."""
    numbering = _flow_numbering(app_state)
    changed = []
    for kind, doc_key, file_key in (("dev", "dev", "file"), ("op", "operator", "op_file")):
        target = Path(repo) / app_state["docs"][doc_key]
        for flow_id, num in numbering.items():
            if target.is_dir():
                want = target / num[file_key]
                found = [p for p in want.parent.glob("[0-9][0-9]-%s.md" % flow_id)] if want.parent.exists() else []
                if not found:
                    continue
                if found[0] != want:
                    found[0].rename(want)
                    changed.append(want.relative_to(repo).as_posix())
                paths = [want]
            else:
                paths = [target] if target.is_file() else []
            for path in paths:
                lines = path.read_text(encoding="utf-8").split("\n")
                for i, line in enumerate(lines):
                    if line.strip() == '<!-- docgen:section id="app-flow/%s" -->' % flow_id:
                        j = next((k for k in range(i + 1, min(i + 4, len(lines))) if lines[k].startswith("###")), None)
                        if j is not None:
                            new = FLOW_HEADING_RE.sub(lambda m: "%s%s%s" % (m.group(1), num[kind], m.group(2)), lines[j])
                            if new != lines[j]:
                                lines[j] = new
                                path.write_text("\n".join(lines), encoding="utf-8")
                                changed.append("%s:%s" % (kind, flow_id))
                        break
    return changed


def cmd_assemble(args):
    """Merge finished flow fragments into the guides, the facts file and the app state, then render.
    The orchestrator runs this once after an app's flow agents are done; fragments are removed after."""
    import docs_render
    repo = Path(args.repo).resolve()
    app_state_path = Path(args.app_state)
    app_state = load_json(app_state_path)
    app_id = app_state["app_id"]
    app_dir = repo / DOCS_DIR / app_id
    numbering = _flow_numbering(app_state)
    facts = docs_render.load_facts(repo, app_id)
    done, problems = [], []
    for frag_dir in sorted(_work(repo, "fragments", app_id).glob("*")) if _work(repo, "fragments", app_id).exists() else []:
        flow_id = frag_dir.name
        try:
            for kind, doc_key, file_key in (("dev", "dev", "file"), ("op", "operator", "op_file")):
                story = frag_dir / ("story-%s.md" % kind)
                if story.exists() and not (frag_dir / ("%s.md" % kind)).exists():
                    _replace_story(repo / app_state["docs"][doc_key], numbering.get(flow_id, {}).get(file_key), flow_id,
                                   story.read_text(encoding="utf-8"))
                    continue
                text = (frag_dir / ("%s.md" % kind)).read_text(encoding="utf-8")
                if not text.lstrip().startswith('<!-- docgen:section id="app-flow/%s" -->' % flow_id):
                    raise ValueError("%s.md doesn't start with the app-flow/%s anchor" % (kind, flow_id))
                target = repo / app_state["docs"][doc_key]
                if target.is_dir():
                    dest = target / numbering.get(flow_id, {}).get(file_key, "05-app-flow/99-%s.md" % flow_id)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    for old in dest.parent.glob("[0-9][0-9]-%s.md" % flow_id):
                        if old != dest:
                            old.unlink()   # its number changed: one file per flow, or Docmost gets the stale copy
                    dest.write_text(_rewrite_image_paths(text, dest, app_dir).rstrip("\n") + "\n", encoding="utf-8")
                else:
                    _place_section(target, "app-flow/%s" % flow_id, _rewrite_image_paths(text, target, app_dir))
            if (frag_dir / "facts.json").exists():
                facts = docs_render.merge_facts(facts, load_json(frag_dir / "facts.json"), flow_id)
            if (frag_dir / "state.json").exists():
                part = load_json(frag_dir / "state.json")
                app_state.setdefault("sections", {}).update(part.get("sections", {}))
                for flow in app_state.get("flows", []):
                    if flow["id"] == flow_id:
                        flow.update(part.get("flow", {}))
            done.append(flow_id)
            shutil.rmtree(frag_dir)
        except (OSError, ValueError, KeyError) as error:
            problems.append({"flow": flow_id, "error": str(error)})
    renumbered = _renumber_flows(repo, app_state)
    _stamp(repo, app_state)
    facts_file = docs_render.facts_path(repo, app_id)
    facts_file.parent.mkdir(parents=True, exist_ok=True)
    save_json(facts_file, facts)
    save_json(app_state_path, app_state)
    rendered = docs_render.render_app(repo, app_state)
    emit({"assembled": done, "problems": problems, "renumbered": renumbered, "rendered": len(rendered["changed"]),
          "missing_blocks": rendered["missing_blocks"]}, 1 if problems else 0)


def cmd_render(args):
    """Fill every docgen:render block in both guides from docs/.docgen/facts/<app>.json."""
    import docs_render
    repo = Path(args.repo).resolve()
    report = docs_render.render_app(repo, load_json(args.app_state), check=args.check, refresh_owners=args.refresh_owners)
    emit(dict(report, ok=not report["missing_blocks"] and not (args.check and report["changed"])),
         1 if args.check and (report["changed"] or report["missing_blocks"]) else 0)


# ---------------------------------------------------------------- usage

def _transcript_dirs():
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"
    return [base] if base.is_dir() else []


def cmd_usage_spend(args):
    """Real token spend of a run, from Claude Code's session transcripts (~/.claude/projects/**.jsonl):
    every assistant message's usage, deduplicated by message id, since the run started, for sessions
    whose working directory is this repo. Split by transcript (the main session and each subagent)."""
    repo = str(Path(args.repo).resolve())
    since = args.since
    seen, per_file = set(), {}
    for base in _transcript_dirs():
        for path in base.rglob("*.jsonl"):
            try:
                modified = datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc)
                if modified.strftime("%Y-%m-%dT%H:%M:%SZ") < since:
                    continue
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
                usage = message.get("usage")
                if not usage or (entry.get("timestamp") or "") < since:
                    continue
                if entry.get("cwd") and not str(entry["cwd"]).startswith(repo):
                    continue
                key = message.get("id") or entry.get("requestId") or entry.get("uuid")
                if key in seen:
                    continue
                seen.add(key)
                row = per_file.setdefault(str(path), {"model": message.get("model"), "messages": 0, "input": 0, "output": 0,
                                                      "cache_write": 0, "cache_read": 0,
                                                      "subagent": bool(entry.get("isSidechain")) or "subagent" in str(path)})
                row["messages"] += 1
                row["input"] += usage.get("input_tokens") or 0
                row["output"] += usage.get("output_tokens") or 0
                row["cache_write"] += usage.get("cache_creation_input_tokens") or 0
                row["cache_read"] += usage.get("cache_read_input_tokens") or 0
    if not per_file:
        emit({"error": "no transcript entries since %s for %s (looked in %s)" % (since, repo, [str(d) for d in _transcript_dirs()]),
              "note": "token figures from agent completion notices are final context size, not spend"}, 2)
    keys = ("input", "output", "cache_write", "cache_read")
    totals = {k: sum(r[k] for r in per_file.values()) for k in keys}
    by_model = {}
    for r in per_file.values():
        m = by_model.setdefault(r["model"] or "?", dict.fromkeys(keys, 0))
        for k in keys:
            m[k] += r[k]
    emit({"since": since, "transcripts": len(per_file), "totals": totals, "by_model": by_model,
          "agents": sorted(({"file": Path(f).name, **r} for f, r in per_file.items()), key=lambda r: -r["output"])})


# ---------------------------------------------------------------- upgrades and skills

# Rough token costs per unit of work, for the opt-in prompt only. They're estimates, not budgets.
COST = {"new_section": 25_000, "facts_app": 40_000, "fresh_app": 150_000, "important_flow": 60_000, "diagram": 12_000, "story": 30_000, "op_section": 4_000}


def cmd_upgrade_plan(args):
    repo = Path(args.repo).resolve()
    state = load_json(repo / DOCS_DIR / ".docgen" / "state.json")
    apps = []
    for app_id in sorted(state.get("apps", {})):
        app_file = repo / DOCS_DIR / ".docgen" / "apps" / ("%s.json" % app_id)
        if app_file.exists():
            apps.append(load_json(app_file))
    pending = []
    # template steps are counted per app: an app converted early (it had drift) isn't counted again
    by_step, regenerate = {}, []
    for a in apps:
        steps = template_path(app_template(a, state))
        if steps is None:
            regenerate.append(a)
            continue
        for step in steps:
            by_step.setdefault((step["from"], step["to"], step["action"]), (step, []))[1].append(a["app_id"])
    for (frm, to, action), (step, ids) in sorted(by_step.items()):
        if action == "extend":
            new = step["sections"].get("op", []) + step["sections"].get("dev", [])
            pending.append({"action": "extend", "sections": step["sections"], "apps": ids,
                            "what": "template %s → %s: add the %s sections" % (frm, to, ", ".join(new)),
                            "units": "%d apps × %d sections" % (len(ids), len(new)), "tokens": len(ids) * len(new) * COST["new_section"]})
        elif action == "facts":
            pending.append({"action": "facts", "apps": ids,
                            "what": "template %s → %s: move every table and list into a facts file, rendered by script from then on" % (frm, to),
                            "units": "%d apps" % len(ids), "tokens": len(ids) * COST["facts_app"]})
    if regenerate:
        flows = sum(1 for a in regenerate for f in a.get("flows", []) if f.get("important") and f.get("status", "active") == "active")
        pending.append({"action": "regenerate", "apps": [a["app_id"] for a in regenerate],
                        "what": "template → %s: regenerate every section" % TEMPLATE_VERSION,
                        "units": "%d apps, %d important flows" % (len(regenerate), flows),
                        "tokens": len(regenerate) * COST["fresh_app"] + flows * COST["important_flow"]})
    else:
        flows = sum(1 for a in apps for f in a.get("flows", []) if f.get("important") and f.get("status", "active") == "active")
        diagrams = sum(1 for a in apps for sec in a.get("sections", {}).values() if sec.get("diagram") in ("drawio", "mermaid"))
        op_sections = sum(1 for a in apps for key in a.get("sections", {}) if key.startswith("op:"))
        if state.get("diagram_version") != DIAGRAM_VERSION:
            pending.append({"action": "redraw", "what": "diagrams %s → %s: redraw every diagram" % (state.get("diagram_version"), DIAGRAM_VERSION),
                            "units": "%d diagram sections, %d stories" % (diagrams, flows),
                            "tokens": diagrams * COST["diagram"] + flows * COST["story"] // 2})
        if state.get("story_version", 1) != STORY_VERSION:
            pending.append({"action": "restory", "what": "stories %s → %s: re-read the code and rewrite every sequence story" % (state.get("story_version", 1), STORY_VERSION),
                            "units": "%d stories" % flows, "tokens": flows * COST["story"]})
        if state.get("humanizer_version") != HUMANIZER_VERSION:
            pending.append({"action": "rehumanize", "what": "humanizer %s → %s: re-polish the flagged User Guide paragraphs" % (state.get("humanizer_version"), HUMANIZER_VERSION),
                            "units": "%d User Guide sections" % op_sections, "tokens": op_sections * COST["op_section"]})
    emit({"pending": pending, "total_tokens": sum(p["tokens"] for p in pending),
          "free": "docs_tool.py migrate already applied the mechanical changes (subtitles, code links, page keys); they cost nothing",
          "note": "rough estimates; the real cost depends on the size of the code"})


def cmd_skill_pin(args):
    """Record which version of an outside skill was used; report when it changed since the last run."""
    repo = Path(args.repo).resolve()
    skill_dir = Path(args.dir).expanduser().resolve()
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        emit({"error": "no SKILL.md in %s" % skill_dir}, 2)
    pin = {"sha256": hashlib.sha256(skill_md.read_bytes()).hexdigest()[:16],
           "commit": git(skill_dir, "rev-parse", "--short=10", "HEAD", check=False).strip() or None}
    state_path = repo / DOCS_DIR / ".docgen" / "state.json"
    state = load_json(state_path)
    previous = state.setdefault("skills", {}).get(args.name)
    state["skills"][args.name] = pin
    save_json(state_path, state)
    emit({"name": args.name, "pin": pin, "previous": previous, "changed": previous is not None and previous != pin})


def _clip_file_ref(path):
    """Put the file itself (not its text) on the clipboard, like copying it in a file manager."""
    path = str(Path(path).resolve())
    if sys.platform == "darwin" and shutil.which("osascript"):
        cmd = ["osascript", "-e", 'set the clipboard to (POSIX file "%s")' % path.replace('"', '\\"')]
    elif shutil.which("powershell.exe"):
        win = subprocess.run(["wslpath", "-w", path], capture_output=True, text=True).stdout.strip() if shutil.which("wslpath") else path
        cmd = ["powershell.exe", "-NoProfile", "-Command", "Set-Clipboard -LiteralPath '%s'" % win.replace("'", "''")]
    elif shutil.which("xclip"):
        cmd = None
        proc = subprocess.run(["xclip", "-selection", "clipboard", "-t", "text/uri-list"], input="file://%s\n" % path, text=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        emit({"ok": proc.returncode == 0, "tool": "xclip"}, 0 if proc.returncode == 0 else 2)
    else:
        emit({"error": "no tool to put a file on the clipboard (osascript, powershell or xclip)"}, 2)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    emit({"ok": proc.returncode == 0, "tool": cmd[0], "stderr": proc.stderr.strip()[:200]}, 0 if proc.returncode == 0 else 2)


def cmd_clip(args):
    """Put a file's text on the OS clipboard, so page content goes to the browser without passing through the model."""
    if args.file_ref:
        _clip_file_ref(args.file)
    text = Path(args.file).read_text(encoding="utf-8")
    candidates = []
    if sys.platform == "darwin":
        candidates.append(["pbcopy"])
    if shutil.which("powershell.exe") or sys.platform.startswith("win"):
        path = args.file
        if shutil.which("wslpath"):
            path = subprocess.run(["wslpath", "-w", args.file], capture_output=True, text=True).stdout.strip()
        candidates.append(["powershell.exe", "-NoProfile", "-Command",
                           "Set-Clipboard -Value (Get-Content -Raw -Encoding UTF8 -LiteralPath '%s')" % path.replace("'", "''")])
    candidates += [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
    for cmd in candidates:
        if not shutil.which(cmd[0]):
            continue
        feed = None if cmd[0] == "powershell.exe" else text.encode("utf-8")
        # xclip and xsel leave a background process holding the clipboard: don't wait on its pipes.
        # pbcopy decodes by locale, so force UTF-8 or arrows and dots come out garbled.
        env = dict(os.environ, LC_CTYPE="UTF-8") if cmd[0] == "pbcopy" else None
        try:
            proc = subprocess.run(cmd, input=feed, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, timeout=10)
        except subprocess.TimeoutExpired:
            continue
        if proc.returncode == 0:
            emit({"ok": True, "tool": cmd[0], "chars": len(text)})
    emit({"error": "no clipboard tool found (pbcopy, powershell, wl-copy, xclip or xsel)"}, 2)


# ---------------------------------------------------------------- svg-theme

LIGHT_DARK_RE = re.compile(r"light-dark\(\s*((?:[^(),]|\([^()]*\))+?)\s*,\s*((?:[^(),]|\([^()]*\))+?)\s*\)")
THEME_STYLE_RE = re.compile(r'<style id="docgen-theme"[^>]*>.*?</style>', re.S)
SVG_OPEN_RE = re.compile(r"<svg\b[^>]*>")


def _rgb(hex_color):
    value = hex_color.lstrip("#")
    return "rgb(%d, %d, %d)" % tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _theme_css(mode):
    """CSS appended to each diagram: light card always; dark palette only in adaptive mode."""
    css = [":root { background-color: #FFFFFF; color-scheme: light; }",
           # "Helvetica" alone falls back to a serif font where it isn't installed (Windows)
           "foreignObject div, text { font-family: Helvetica, Arial, 'Liberation Sans', sans-serif !important; }"]
    if mode != "adaptive":
        return "\n".join(css)
    rules = [":root { background-color: %s !important; }" % DARK_BACKGROUND,
             # every label light by default, including labels whose color draw.io left unset
             "foreignObject div { color: %s !important; }" % DARK_TEXT["#1A1A1A"],
             "text { fill: %s !important; }" % DARK_TEXT["#1A1A1A"]]
    for light, dark in DARK_FILL.items():
        rules.append('[fill="%s" i], [fill="%s"] { fill: %s !important; }' % (light, _rgb(light), dark))
        rules.append('[style*="background-color: %s" i], [style*="background-color: %s"] { background-color: %s !important; }'
                     % (light, _rgb(light), dark if light != "#FFFFFF" else DARK_BACKGROUND))
    for light, dark in DARK_STROKE.items():
        rules.append('[stroke="%s" i], [stroke="%s"] { stroke: %s !important; }' % (light, _rgb(light), dark))
    for light, dark in DARK_TEXT.items():
        # "; color:" / leading "color:" so background-color never matches
        rules.append('[style^="color: %s" i], [style*="; color: %s" i], [style^="color: %s"], [style*="; color: %s"] { color: %s !important; }'
                     % (light, light, _rgb(light), _rgb(light), dark))
    return "\n".join(css + ["@media (prefers-color-scheme: dark) {"] + ["  " + r for r in rules] + ["}"])


def apply_theme(svg_text, mode):
    """Return svg_text with draw.io's own light-dark() adaptation removed and the docgen theme style set."""
    text = LIGHT_DARK_RE.sub(lambda m: m.group(1), svg_text)
    text = text.replace("color-scheme: light dark", "color-scheme: light")
    text = THEME_STYLE_RE.sub("", text)
    opening = SVG_OPEN_RE.search(text)
    if not opening:
        raise ValueError("not an SVG")
    style = '<style id="docgen-theme" data-mode="%s">\n%s\n</style>' % (mode, _theme_css(mode))
    return text[:opening.end()] + style + text[opening.end():]


def cmd_svg_theme(args):
    repo = Path(args.repo).resolve()
    state_path = repo / DOCS_DIR / ".docgen" / "state.json"
    state = load_json(state_path) if state_path.exists() else {}
    # The files in docs/ stay adaptive: GitLab shows them too. A Docmost that needs always-light gets
    # light copies made at sync time (sync-plan), so the repo never depends on one viewer's quirks.
    mode = args.mode or "adaptive"
    apps = [args.app] if args.app else sorted(state.get("apps", {}))
    done = []
    for app_id in apps:
        for svg in sorted((repo / DOCS_DIR / app_id / "diagrams").glob("*.drawio.svg")):
            svg.write_text(apply_theme(svg.read_text(encoding="utf-8"), mode), encoding="utf-8")
            done.append(svg.relative_to(repo).as_posix())
    emit({"mode": mode, "themed": len(done), "files": done})


# ---------------------------------------------------------------- migrate

OLD_USER_GUIDE_TITLE = re.compile(r"^# (.+?)(?::| —| –| -) Panduan Operator\s*$")


def _new_subtitle(match):
    sha, dirty, branch, date, name = match.groups()
    return "> generated at `%s`%s on `%s`, %s, run by %s" % (sha, dirty or "", branch, date, name)


def _link_refs(line, base, sha, repo):
    """Wrap plain `path:line` references in GitLab permalinks pinned to `sha`."""
    def wrap(m):
        path, ext, start, end = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        if not _is_code_ref(path, ext, repo):
            return m.group(0)
        return "[%s](%s)" % (m.group(0), permalink(base, sha, path, start, int(end) if end else None))
    out, pos = [], 0
    for linked in LINKED_REF_RE.finditer(line):           # leave existing links alone
        out.append(CODE_REF_RE.sub(wrap, line[pos:linked.start()]))
        out.append(linked.group(0))
        pos = linked.end()
    out.append(CODE_REF_RE.sub(wrap, line[pos:]))
    return "".join(out)


def page_key(app_id, kind, md=None, single=True):
    """Docmost page keys follow the doc structure, not file paths, so a split or a renamed file keeps its page."""
    short = "dev" if kind == "dev" else "op"
    if md is None or single:
        return "%s/%s" % (app_id, short)
    for line in Path(md).read_text(encoding="utf-8").splitlines():
        m = ANCHOR_RE.match(line.strip())
        if m:
            return "%s/%s/%s" % (app_id, short, m.group(1))
    return "%s/%s/file:%s" % (app_id, short, Path(md).stem)


def cmd_migrate(args):
    """Bring docs written by older plugin versions up to current conventions. Idempotent, no LLM:
    the "User Guide" title, the "generated at … run by …" subtitle, GitLab permalinks for code
    references, and Docmost page keys based on doc structure instead of file paths."""
    repo = Path(args.repo).resolve()
    state_path = repo / DOCS_DIR / ".docgen" / "state.json"
    report = {"titles": [], "subtitles": 0, "links": 0, "page_keys": {}, "notes": []}
    if not state_path.exists():
        emit(report)
    state = load_json(state_path)
    base = web_url(repo)
    if base is None:
        report["notes"].append("no 'origin' remote: code references left as plain text")
    for app_id in sorted(state.get("apps", {})):
        app_file = repo / DOCS_DIR / ".docgen" / "apps" / ("%s.json" % app_id)
        if not app_file.exists():
            continue
        app_state = load_json(app_file)
        sections = app_state.get("sections", {})
        for kind in ("dev", "operator"):
            target = repo / app_state.get("docs", {}).get(kind, "__none__")
            for md in ([target] if target.is_file() else sorted(target.rglob("*.md")) if target.is_dir() else []):
                doc = Doc(md, repo)
                lines = list(doc.lines)
                changed = False
                for i, line in enumerate(lines):
                    title = OLD_USER_GUIDE_TITLE.match(line) if kind == "operator" else None
                    if title:
                        lines[i] = "# %s: User Guide" % title.group(1)
                        report["titles"].append(doc.rel)
                        changed = True
                        continue
                    sub = OLD_SUBTITLE_RE.match(line.strip())
                    if sub:
                        lines[i] = _new_subtitle(sub)
                        report["subtitles"] += 1
                        changed = True
                        continue
                    if kind == "dev" and base and CODE_REF_RE.search(line):
                        sha = sections.get("dev:%s" % doc.section_at(i), {}).get("sha")
                        if sha:
                            new = _link_refs(line, base, sha, repo)
                            if new != line:
                                report["links"] += new.count("](") - line.count("](")
                                lines[i] = new
                                changed = True
                if changed:
                    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Docmost page keys: file paths → structure keys (keeps each page's URL)
        pages = state.get("docmost", {}).get("pages", {})
        for old in [k for k in list(pages) if k.startswith(app_id + "/")]:
            new = None
            if old == "%s/operator" % app_id:
                new = "%s/op" % app_id
            elif old.endswith(".md") and (repo / DOCS_DIR / old).is_file():
                md = repo / DOCS_DIR / old
                for kind in ("dev", "operator"):
                    target = repo / app_state["docs"][kind]
                    if md == target or (target.is_dir() and target in md.parents):
                        new = page_key(app_id, kind, md, single=target.is_file())
            if new and new != old and new not in pages:
                pages[new] = pages.pop(old)
                report["page_keys"][old] = new
        # 3.0: the Dev Guide lives in GitLab only. Forget its pages without asking; nothing in Docmost is touched.
        images = state.get("docmost", {}).get("images", {})
        for key in [k for k in list(pages) if k == "%s/dev" % app_id or k.startswith("%s/dev/" % app_id)]:
            pages.pop(key)
            report["dev_pages_dropped"] = report.get("dev_pages_dropped", 0) + 1
            for digest in [h for h, v in images.items() if v.get("page") == key]:
                images.pop(digest)
    if report["page_keys"] or report.get("dev_pages_dropped"):
        save_json(state_path, state)
    emit(report)


# ---------------------------------------------------------------- readme

def _codeowner_match(pattern, target):
    if pattern in ("*", "/*", "/**", "**"):
        return True
    anchored = pattern.startswith("/")
    p = pattern.strip("/")
    if any(ch in p for ch in "*?["):
        candidates = [target.strip("/")] if anchored else [target.strip("/")] + ["/".join(target.strip("/").split("/")[i:]) for i in range(1, target.count("/"))]
        return any(fnmatch.fnmatch(c, p) or fnmatch.fnmatch(c, p + "/*") for c in candidates)
    # a directory pattern owns everything under it, so "/services/pay" must not own "/services/pay-v2"
    if anchored:
        return target == "/%s/" % p or target.startswith("/%s/" % p)
    return ("/%s/" % p) in target


def _codeowners(repo, root):
    """Owners for the app root from the first CODEOWNERS GitLab would use (root, docs/, .gitlab/).
    Within each [section] the last matching rule wins; sections add up, as in GitLab."""
    for candidate in ("CODEOWNERS", "docs/CODEOWNERS", ".gitlab/CODEOWNERS"):
        path = Path(repo) / candidate
        if not path.is_file():
            continue
        target = "/" + root.strip("/") + "/" if root not in (".", "") else "/"
        per_section, section, defaults = {}, "", []
        for line in _read(path).splitlines():
            line = line.split(" #", 1)[0].strip()
            if not line or line.startswith("#"):
                continue
            header = re.match(r"^\^?\[([^\]]+)\](?:\[\d+\])?\s*(.*)$", line)
            if header:
                section, defaults = header.group(1).lower(), header.group(2).split()
                continue
            parts = line.split()
            if _codeowner_match(parts[0], target):
                per_section[section] = parts[1:] or defaults
        owners = []
        for names in per_section.values():
            owners += [n for n in names if n not in owners]
        # GitLab stops at the first CODEOWNERS file it finds, even when no rule matches
        return {"source": candidate, "owners": owners} if owners else None
    return None


def _top_committers(repo, root, limit=3):
    out = git(repo, "shortlog", "-sne", "--since=6.months", "HEAD", "--", root if root not in ("", ".") else ".", check=False)
    people = []
    for line in out.splitlines()[:limit]:
        count, _, who = line.strip().partition("\t")
        people.append({"who": who.strip(), "commits": int(count or 0)})
    return {"source": "git history, last 6 months", "owners": people} if people else None


def cmd_owners(args):
    """Owners and escalation target for one app (conventions §11): CODEOWNERS is both; otherwise
    recent committers own it and escalation is unknown."""
    repo = Path(args.repo).resolve()
    found = _codeowners(repo, args.root)
    if found:
        emit({"owners": found["owners"], "escalation": found["owners"], "source": found["source"]})
    committers = _top_committers(repo, args.root)
    emit({"owners": [c["who"] for c in committers["owners"]] if committers else [],
          "escalation": None, "source": committers["source"] if committers else None})


def cmd_readme_plan(args):
    emit(_readme_plan(Path(args.repo).resolve()))


def cmd_readme(args):
    """Rewrite every app README (and a monorepo root index) from the Dev Guides and facts. No model."""
    import docs_render
    repo = Path(args.repo).resolve()
    plan = _readme_plan(repo)
    if plan["missing_dev_guide"]:
        emit({"error": "no finished Dev Guide for: %s" % ", ".join(plan["missing_dev_guide"])}, 2)
    written, corrected, infos = [], {}, {}
    for entry in plan["apps"]:
        app_state = load_json(repo / DOCS_DIR / ".docgen" / "apps" / ("%s.json" % entry["app_id"]))
        text, fixes, infos[entry["app_id"]] = docs_render.app_readme(repo, entry, app_state)
        (repo / entry["readme"]).write_text(text, encoding="utf-8")
        written.append(entry["readme"])
        if fixes:
            corrected[entry["app_id"]] = fixes
    if plan["root_index"] and not any(e["readme"] == "README.md" for e in plan["apps"]):
        (repo / "README.md").write_text(docs_render.root_readme(repo, plan, infos), encoding="utf-8")
        written.append("README.md")
    emit({"written": written, "old_readme_claims_corrected": corrected,
          "no_docmost_link": [e["app_id"] for e in plan["apps"] if not e.get("docmost_url")]})


def _readme_plan(repo):
    state_path = repo / DOCS_DIR / ".docgen" / "state.json"
    if not state_path.exists():
        emit({"error": "no docs/.docgen/state.json: run /app-docs:generate first"}, 2)
    state = load_json(state_path)
    head = git(repo, "rev-parse", "HEAD").strip()
    pages = state.get("docmost", {}).get("pages", {})
    apps, missing = [], []
    for app_id, app in sorted(state.get("apps", {}).items()):
        app_file = repo / DOCS_DIR / ".docgen" / "apps" / ("%s.json" % app_id)
        app_state = load_json(app_file) if app_file.exists() else {}
        dev = repo / app_state.get("docs", {}).get("dev", "__none__")
        if app.get("stage") != "done" or not (dev.is_file() or dev.is_dir()):
            missing.append(app_id)
            continue
        sections = [sec for sec in app_state.get("sections", {}).values() if sec.get("status") != "removed"]
        # the oldest section decides how current the README can claim to be
        latest = min(sections, key=lambda sec: (sec.get("date", ""), sec.get("sha", "")), default={})
        verified = latest.get("sha", "")
        behind = git(repo, "rev-list", "--count", "%s..HEAD" % verified, check=False).strip() if verified else ""
        root = app_state.get("root", app.get("root", "."))
        readme = (repo / root / "README.md") if root not in ("", ".") else repo / "README.md"

        def rel(target):
            return os.path.relpath(repo / target, readme.parent).replace(os.sep, "/")
        structure = repo / DOCS_DIR / app_id / "diagrams" / "structure.drawio.svg"
        apps.append({
            "app_id": app_id, "root": root, "readme": readme.relative_to(repo).as_posix(),
            "dev_guide": rel(app_state["docs"]["dev"]), "user_guide": rel(app_state["docs"]["operator"]),
            "structure_diagram": rel(structure.relative_to(repo).as_posix()) if structure.exists() else None,
            "docmost_url": pages.get(app_id, {}).get("url"),
            "verified_sha": verified, "verified_date": latest.get("date"), "verified_branch": latest.get("branch"),
            "head_sha": head, "commits_since_verified": int(behind) if behind.isdigit() else None,
            "sections_not_at_head": sum(1 for sec in sections if sec.get("sha") != head or sec.get("dirty")),
            "owners": _codeowners(repo, root) or _top_committers(repo, root),
        })
    monorepo = len(state.get("apps", {})) > 1 or any(a["root"] not in ("", ".") for a in apps)
    return ({
        "head_sha": head, "dirty": bool(changed_paths_outside_docs(repo)),
        "apps": apps, "missing_dev_guide": missing,
        "root_index": {"readme": "README.md", "owners": _codeowners(repo, ".") or _top_committers(repo, ".")} if monorepo else None,
        "docs_behind_head": [a["app_id"] for a in apps if a["verified_sha"] != head],
    })


# ---------------------------------------------------------------- sync

NUMBERED_ITEM_RE = re.compile(r"^(\s*)(\d+)\.\s+")


def _image_hash(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None


MD_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)")


def _upload_copy(image, theme, work):
    """The file to upload for one diagram: the repo's own, or a light copy when Docmost's toggle doesn't reach images."""
    if theme != "light" or not image.name.endswith(".drawio.svg") or not image.is_file():
        return image
    copy = work / "images" / image.name
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text(apply_theme(image.read_text(encoding="utf-8"), "light"), encoding="utf-8")
    return copy


def _prepare_markdown(path, bold_numbers=False, uploaded=None, theme="adaptive", work=None, links=None):
    """Strip docgen anchors and the H1; swap drawio images for upload placeholders, or, when the same
    file was already uploaded to Docmost (`uploaded`: content hash → url), for a link to that upload.
    `links(target, source)` turns a markdown link target into a Docmost URL, "" for plain text, or None to leave it.
    Returns (text, [abs image paths to upload], [(name, hash)] of every image in page order, links left as text)."""
    images, order = [], []
    out = []
    pending = []
    title_dropped = False
    in_fence = False
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if bold_numbers and not in_fence:
            # Docmost renumbered lists from 1 at calibration: keep arrow numbers as plain bold text
            line = NUMBERED_ITEM_RE.sub(lambda m: "%s**%s.** " % (m.group(1), m.group(2)), line)
        if ANCHOR_RE.match(line.strip()) or re.match(r"^<!--\s*/?(docgen:(render|flow)|app-docs:keep)\b", line.strip()):
            continue
        if not title_dropped and line.startswith("# "):
            title_dropped = True  # Docmost shows the page title separately
            continue

        def swap(match):
            image = _upload_copy((Path(path).parent / match.group(1)).resolve(), theme, work)
            digest = _image_hash(image)
            order.append((image.name, digest))
            if uploaded and digest in uploaded:
                return "![%s](%s)" % (image.stem, uploaded[digest]["url"])
            images.append(str(image))
            return "[[diagram:%s]]" % image.name

        def link(match):
            url = links(match.group(2), Path(path)) if links else None
            if url is None:
                return match.group(0)
            if url == "":
                pending.append(match.group(2))
                return match.group(1)
            return "[%s](%s)" % (match.group(1), url)
        line = IMAGE_RE.sub(swap, line)
        out.append(line if in_fence else MD_LINK_RE.sub(link, line))
    return "\n".join(out).strip() + "\n", images, order, pending


PASTE_JS = r"""(async () => {
  // Generated by docs_tool.py sync-plan. Replaces the page title and body of the open Docmost page.
  const title = %(title)s;
  const markdown = %(markdown)s;
  const images = %(images)s;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const paste = (el, dt) => el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
  const editors = [...document.querySelectorAll('.ProseMirror[contenteditable="true"]')];
  if (editors.length < 2) return JSON.stringify({ok: false, error: 'expected title + body editors, found ' + editors.length});
  const [titleEl, body] = [editors[0], editors[editors.length - 1]];
  titleEl.focus(); document.execCommand('selectAll'); document.execCommand('insertText', false, title);
  await sleep(300);
  body.focus(); document.execCommand('selectAll');
  const text = new DataTransfer(); text.setData('text/plain', markdown); paste(body, text);
  await sleep(1500);
  const report = [];
  for (const img of images) {
    const token = '[[diagram:' + img.name + ']]';
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    let node = null, hit = -1;
    while ((node = walker.nextNode()) && (hit = node.textContent.indexOf(token)) < 0) {}
    if (!node) { report.push(img.name + ': placeholder not found'); continue; }
    const range = document.createRange(); range.setStart(node, hit); range.setEnd(node, hit + token.length);
    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
    await sleep(200); document.execCommand('delete');
    const bytes = Uint8Array.from(atob(img.b64), c => c.charCodeAt(0));
    const files = new DataTransfer(); files.items.add(new File([bytes], img.name, {type: img.mime})); paste(body, files);
    await sleep(3000);
    report.push(img.name + ': pasted');
  }
  const out = body.innerText;
  return JSON.stringify({ok: true, body_chars: out.length,
    literal_markdown: /^(#{1,6} |\|\s*-{3})/m.test(out),
    leftover_placeholders: (out.match(/\[\[diagram:/g) || []).length,
    images: report, img_elements: body.querySelectorAll('img').length});
})()
"""


def _paste_js(title, text, images):
    import base64
    payload = [{"name": Path(i).name, "mime": "image/svg+xml",
                "b64": base64.b64encode(Path(i).read_bytes()).decode()} for i in images if Path(i).is_file()]
    return PASTE_JS % {"title": json.dumps(title, ensure_ascii=False),
                       "markdown": json.dumps(text, ensure_ascii=False),
                       "images": json.dumps(payload)}


def _title(path, fallback):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


TITLE_SEPARATORS = (": ", " — ", " – ", " - ")


def _app_name(repo, app_state, app_id):
    """Display name from the dev doc's H1 ("Payment API — Dev Guide" → "Payment API"), else the app id."""
    target = repo / app_state["docs"]["dev"]
    first = target if target.is_file() else next(iter(sorted(target.rglob("*.md"))), None) if target.is_dir() else None
    heading = _title(first, "") if first else ""
    for sep in TITLE_SEPARATORS:
        if sep in heading:
            return heading.split(sep, 1)[0].strip() or app_id
    return app_id


def _subpage_title(title, app_name):
    """Only the app's own page carries the app name in Docmost; sub-pages drop an "<app name><sep>" prefix."""
    for sep in TITLE_SEPARATORS:
        prefix = app_name + sep
        if title.lower().startswith(prefix.lower()) and title[len(prefix):].strip():
            return title[len(prefix):].strip()
    return title


PREPARE_JS = r"""(() => {
  // Sets the page title, then focuses the body and selects all of it, ready for a clipboard paste.
  const title = %(title)s;
  const eds = [...document.querySelectorAll('.ProseMirror[contenteditable="true"]')];
  if (eds.length < 2) return JSON.stringify({ok: false, error: 'expected title + body editors, found ' + eds.length});
  const [t, b] = [eds[0], eds[eds.length - 1]];
  t.focus(); document.execCommand('selectAll'); document.execCommand('insertText', false, title);
  b.focus(); document.execCommand('selectAll');
  return JSON.stringify({ok: true});
})()
"""

IMAGES_JS = r"""(() => {
  // Lists the image addresses in the page body, in order, for sync-record --image-urls.
  const eds = [...document.querySelectorAll('.ProseMirror[contenteditable="true"]')];
  const body = eds[eds.length - 1];
  return JSON.stringify([...body.querySelectorAll('img')].map(i => i.getAttribute('src')));
})()
"""

CHECK_JS = r"""(() => {
  // Reports what the open page body holds, so sync can confirm instead of waiting on timers.
  const expect = %(expect)s;
  const eds = [...document.querySelectorAll('.ProseMirror[contenteditable="true"]')];
  const body = eds[eds.length - 1];
  if (!body) return JSON.stringify({ok: false, error: 'no editor'});
  const text = body.innerText;
  const imgs = [...body.querySelectorAll('img')];
  const uploaded = imgs.filter(i => /^https?:|^\//.test(i.getAttribute('src') || '') && !/^blob:|^data:/.test(i.src)).length;
  const headings = body.querySelectorAll('h1,h2,h3,h4,h5,h6').length;
  const lists = body.querySelectorAll('ol').length;
  const placeholders = (text.match(/\[\[diagram:/g) || []).length;
  const literal = /^(#{1,6} |\|\s*-{3})/m.test(text);
  const ok = !literal && placeholders <= expect.placeholders_left && uploaded >= expect.images && headings >= expect.headings;
  return JSON.stringify({ok, body_chars: text.length, headings, ordered_lists: lists, images_uploaded: uploaded,
                         images_total: imgs.length, placeholders, literal_markdown: literal, title: (eds[0] || {}).innerText});
})()
"""

PLACE_JS = r"""(() => {
  // Selects and deletes one diagram placeholder, leaving the cursor where the image goes.
  const token = %(token)s;
  const eds = [...document.querySelectorAll('.ProseMirror[contenteditable="true"]')];
  const body = eds[eds.length - 1];
  const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
  let node = null, hit = -1;
  while ((node = walker.nextNode()) && (hit = node.textContent.indexOf(token)) < 0) {}
  if (!node) return JSON.stringify({ok: false, error: 'placeholder not found'});
  body.focus();
  const range = document.createRange(); range.setStart(node, hit); range.setEnd(node, hit + token.length);
  const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
  document.execCommand('delete');
  return JSON.stringify({ok: true});
})()
"""

IMAGE_JS = r"""(() => {
  // Fallback only: pastes one image from base64 at the cursor (used when clipboard and file upload don't work).
  const img = %(image)s;
  const eds = [...document.querySelectorAll('.ProseMirror[contenteditable="true"]')];
  const body = eds[eds.length - 1];
  const bytes = Uint8Array.from(atob(img.b64), c => c.charCodeAt(0));
  const files = new DataTransfer(); files.items.add(new File([bytes], img.name, {type: img.mime}));
  body.dispatchEvent(new ClipboardEvent('paste', {clipboardData: files, bubbles: true, cancelable: true}));
  return JSON.stringify({ok: true});
})()
"""


def _heading_count(markdown):
    count, in_fence = 0, False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and re.match(r"^#{1,6} ", line):
            count += 1
    return count


# ---------------------------------------------------------------- workspace (several repos in one parent folder)

WORKSPACE_FILE = ".app-docs-workspace.json"
# Docmost facts that are the same for every repo synced to one Docmost: calibrated once per workspace
CALIBRATION_KEYS = ("root_url", "method", "image_method", "diagram_theme", "list_numbers", "image_reuse")


def find_workspace(repo):
    """The workspace folder and file that list this repo (one or two levels up), else (None, None)."""
    repo = Path(repo).resolve()
    for folder in (repo.parent, repo.parent.parent):
        path = folder / WORKSPACE_FILE
        if path.is_file():
            workspace = load_json(path)
            if any((folder / r["path"]).resolve() == repo for r in workspace.get("repos", [])):
                return folder, workspace
    return None, None


def docmost_settings(repo, state):
    """The repo's Docmost settings. Inside a workspace, the workspace's calibration wins: it's the latest one
    for that Docmost, while a repo keeps whatever was true when it was last synced."""
    settings = dict(state.get("docmost", {}))
    _, workspace = find_workspace(repo)
    for key in CALIBRATION_KEYS:
        if (workspace or {}).get("docmost", {}).get(key) is not None:
            settings[key] = workspace["docmost"][key]
    return settings


def _op_pages(repo, state):
    """Every Docmost page of a repo's User Guides, in parent-before-child order: (key, parent, title, source md or None).
    The app's own page is the User Guide (single mode) or the top index of a split one."""
    out = []
    for app_id, app in sorted(state.get("apps", {}).items()):
        if app.get("stage") != "done":
            continue
        app_state = load_json(repo / DOCS_DIR / ".docgen" / "apps" / ("%s.json" % app_id))
        app_name = _app_name(repo, app_state, app_id)
        target = repo / app_state["docs"]["operator"]
        if target.is_file():
            out.append((app_id, None, app_name, target))
            continue
        top_index = target / "00-index.md"
        out.append((app_id, None, app_name, top_index if top_index.exists() else None))

        def folder_page(folder):
            # A sub-folder's 00-index.md is that folder's page; its other files hang under it.
            if folder == target:
                return app_id
            index = folder / "00-index.md"
            return page_key(app_id, "operator", index, single=False) if index.exists() else folder_page(folder.parent)

        for md in sorted(target.rglob("*.md")):
            if md == top_index:
                continue
            is_index = md.name == "00-index.md" and md.parent != target
            parent = folder_page(md.parent.parent if is_index else md.parent)
            out.append((page_key(app_id, "operator", md, single=False), parent, _subpage_title(_title(md, md.stem), app_name), md))
    return out


def _link_resolver(repo):
    """links(target, source) for _prepare_markdown: a link to any User Guide file in this repo or its workspace
    becomes that page's Docmost URL, or plain text ("") while that page isn't synced yet. Docs keep ordinary
    relative or GitLab links, so they work in GitLab; only the Docmost copy is rewritten."""
    folder, workspace = find_workspace(repo)
    roots = [Path(repo).resolve()]
    if workspace:
        roots += [(folder / r["path"]).resolve() for r in workspace.get("repos", []) if (folder / r["path"]).resolve() != roots[0]]
    by_file, bases = {}, []
    for root in roots:
        state_path = root / DOCS_DIR / ".docgen" / "state.json"
        if not state_path.is_file():
            continue
        state = load_json(state_path)
        urls = {k: v.get("url") for k, v in state.get("docmost", {}).get("pages", {}).items()}
        for key, _, _, md in _op_pages(root, state):
            if md is not None:
                by_file[md.resolve()] = urls.get(key) or ""
        base = web_url(root)
        if base:
            bases.append((base.rstrip("/") + "/-/blob/", root))

    def resolve(target, source):
        target = target.split("#", 1)[0]
        if not target.endswith(".md"):
            return None
        if target.startswith(("http://", "https://")):
            for prefix, root in bases:
                if target.startswith(prefix):
                    parts = target[len(prefix):].split("/")
                    for i in range(1, len(parts)):  # the ref (branch, tag or sha) may contain slashes
                        found = by_file.get((root / "/".join(parts[i:])).resolve())
                        if found is not None:
                            return found
            return None
        return by_file.get((source.parent / urllib.parse.unquote(target)).resolve())
    return resolve


def cmd_sync_plan(args):
    repo = Path(args.repo).resolve()
    state = load_json(repo / DOCS_DIR / ".docgen" / "state.json")
    docmost = docmost_settings(repo, state)
    synced = docmost.get("pages", {})
    bold_numbers = docmost.get("list_numbers") == "bold"
    theme = docmost.get("diagram_theme") or "adaptive"
    # an image uploaded once (on any page) is linked from every other page, unless calibration found that broken
    uploaded = {} if docmost.get("image_reuse") == "off" else docmost.get("images", {})
    work = repo / DOCS_DIR / ".docgen" / ".work" / "sync"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    links = _link_resolver(repo)
    pages = []

    def add(key, parent, title, source=None):
        text, images, order, pending = _prepare_markdown(source, bold_numbers, uploaded, theme, work, links) if source else ("", [], [], [])
        # Title is part of the hash, so a renamed page is re-synced even when its body didn't change.
        # Resolved links are in the text, so a page whose link target got synced since is re-synced too.
        digest = hashlib.sha256((title + "\n" + text).encode())
        for image in images:
            digest.update(Path(image).read_bytes() if Path(image).is_file() else b"missing")
        base = work / key.replace("/", "__").replace(":", "_")
        prepared = base.with_suffix(".md")
        prepared.write_text(text, encoding="utf-8")
        files = {"prepared_file": str(prepared)}
        for name, template, values in (("prepare_js", PREPARE_JS, {"title": json.dumps(title, ensure_ascii=False)}),
                                       ("check_js", CHECK_JS, {"expect": json.dumps({"images": len(images), "placeholders_left": 0,
                                                                                    "headings": _heading_count(text)})}),
                                       ("images_js", IMAGES_JS, {}),
                                       ("paste_js", None, None), ("paste_text_js", None, None)):
            path = base.with_suffix("." + name.replace("_", "."))
            body = _paste_js(title, text, images if name == "paste_js" else []) if template is None else (template % values if values else template)
            path.write_text(body, encoding="utf-8")
            files[name] = str(path)
        (base.parent / (base.name + ".order.json")).write_text(json.dumps(order), encoding="utf-8")
        image_list = []
        for n, image in enumerate(images, start=1):
            name = Path(image).name
            place = base.with_suffix(".place%d.js" % n)
            place.write_text(PLACE_JS % {"token": json.dumps("[[diagram:%s]]" % name)}, encoding="utf-8")
            entry = {"name": name, "path": image, "place_js": str(place)}
            if Path(image).is_file():
                fallback = base.with_suffix(".image%d.js" % n)
                fallback.write_text(IMAGE_JS % {"image": json.dumps({"name": name, "mime": "image/svg+xml",
                                    "b64": base64.b64encode(Path(image).read_bytes()).decode()})}, encoding="utf-8")
                entry["image_js"] = str(fallback)
            image_list.append(entry)
        entry = {"key": key, "parent": parent, "title": title, "existing_url": synced.get(key, {}).get("url"),
                 "container": source is None, "images": image_list, "images_linked": len(order) - len(images),
                 "links_pending": pending, "content_hash": "sha256:" + digest.hexdigest()}
        entry.update(files)
        entry["changed"] = synced.get(key, {}).get("content_hash") != entry["content_hash"]
        pages.append(entry)

    for key, parent, title, source in _op_pages(repo, state):
        add(key, parent, title, source)
    keys = [p["key"] for p in pages]
    duplicates = sorted({k for k in keys if keys.count(k) > 1})
    if duplicates:
        emit({"error": "two files map to the same Docmost page (same first section anchor): %s. Fix the docs (validate reports anchor-duplicate) before syncing." % ", ".join(duplicates)}, 2)
    planned = {key for key, _, _, _ in _op_pages(repo, state)}
    orphans = [{"key": k, "url": v.get("url")} for k, v in sorted(synced.items()) if k not in planned and v.get("url")]
    emit({"root_url": docmost.get("root_url"),
          "method": docmost.get("method"),
          "image_method": docmost.get("image_method"),
          "diagram_theme": theme,
          "list_numbers": docmost.get("list_numbers"),
          "image_reuse": docmost.get("image_reuse"),
          "pages": pages,
          "to_sync": sum(1 for p in pages if p["changed"]),
          "links_pending": sum(len(p["links_pending"]) for p in pages),
          "orphans": orphans})


def cmd_sync_record(args):
    repo = Path(args.repo).resolve()
    path = repo / DOCS_DIR / ".docgen" / "state.json"
    state = load_json(path)
    docmost = state.setdefault("docmost", {})
    calibration = {}
    for key in CALIBRATION_KEYS:
        value = getattr(args, key)
        if value:
            docmost[key] = calibration[key] = value
    if args.image_reuse == "off":
        docmost.pop("images", None)
    if calibration:
        # the same Docmost serves every repo of a workspace: the next repo starts calibrated
        folder, workspace = find_workspace(repo)
        if workspace is not None:
            workspace.setdefault("docmost", {}).update(calibration)
            save_json(folder / WORKSPACE_FILE, workspace)
    if args.remove_key:
        docmost.setdefault("pages", {}).pop(args.remove_key, None)
        # images uploaded on that page go with it: the next page that needs them uploads them again
        docmost["images"] = {h: v for h, v in docmost.get("images", {}).items() if v.get("page") != args.remove_key}
    if args.key and args.image_urls:
        order_file = repo / DOCS_DIR / ".docgen" / ".work" / "sync" / (args.key.replace("/", "__").replace(":", "_") + ".order.json")
        order = json.loads(order_file.read_text()) if order_file.exists() else []
        urls = json.loads(args.image_urls)
        if len(urls) == len(order):
            for (name, digest), url in zip(order, urls):
                if digest and url and not url.startswith(("blob:", "data:")) and digest not in docmost.get("images", {}):
                    docmost.setdefault("images", {})[digest] = {"url": url, "page": args.key, "name": name}
        else:
            print(json.dumps({"warning": "page has %d images, plan has %d: image addresses not recorded" % (len(urls), len(order))}))
    if args.key and not args.remove_key:
        page = docmost.setdefault("pages", {}).setdefault(args.key, {})
        if args.url:
            page["url"] = args.url
        if args.content_hash:
            page["content_hash"] = args.content_hash
        page["synced_sha"] = git(repo, "rev-parse", "HEAD").strip()
        page["synced_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    save_json(path, state)
    emit({"ok": True})


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("meta", "detect", "drift", "sync-plan", "migrate", "readme-plan", "upgrade-plan"):
        p = sub.add_parser(name)
        p.add_argument("--repo", default=".")
    p = sub.add_parser("author")
    p.add_argument("--repo", default=".")
    p.add_argument("file")
    p.add_argument("start", type=int)
    p.add_argument("end", type=int)
    p = sub.add_parser("validate")
    p.add_argument("--repo", default=".")
    p.add_argument("--app-state", required=True)
    p = sub.add_parser("sync-record")
    p.add_argument("--repo", default=".")
    p.add_argument("--key")
    p.add_argument("--url")
    p.add_argument("--content-hash")
    p.add_argument("--root-url")
    p.add_argument("--method")
    p.add_argument("--diagram-theme", choices=["adaptive", "light"])
    p.add_argument("--list-numbers", choices=["native", "bold"])
    p.add_argument("--image-method", choices=["clipboard-file", "file-upload", "paste-script"])
    p.add_argument("--remove-key", help="forget a page (after it was archived or deleted)")
    p.add_argument("--image-urls", help="images_js output for --key: records each uploaded image's address for reuse")
    p.add_argument("--image-reuse", choices=["ok", "off"], help="calibration result: can pages link to an image uploaded on another page")
    p = sub.add_parser("facts-snapshot")
    p.add_argument("--repo", default=".")
    p.add_argument("--app-state", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--cells", action="store_true", help="also keep every table cell and list item (facts conversion)")
    p = sub.add_parser("facts-diff")
    p.add_argument("--repo", default=".")
    p.add_argument("--app-state", required=True)
    p.add_argument("--before", required=True)
    p.add_argument("--only", choices=["dev", "op"])
    p.add_argument("--strict", action="store_true", help="any change fails (use after the humanizer)")
    p.add_argument("--cells", action="store_true", help="compare cell by cell with a --cells snapshot")
    p = sub.add_parser("readme")
    p.add_argument("--repo", default=".")
    p = sub.add_parser("keep-snapshot")
    p.add_argument("--repo", default=".")
    p.add_argument("--app-state", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("keep-restore")
    p.add_argument("--repo", default=".")
    p.add_argument("--app-state", required=True)
    p.add_argument("--before", required=True)
    p = sub.add_parser("humanize-plan")
    p.add_argument("--repo", default=".")
    p.add_argument("--app-state", required=True)
    p.add_argument("--scope", help="comma-separated op: section keys (default: all)")
    p.add_argument("--skill", help="humanizer-indonesia folder, or none")
    p = sub.add_parser("facts-set")
    p.add_argument("--repo", default=".")
    p.add_argument("--app-state", required=True)
    p.add_argument("--edits", required=True, help="JSON file: [{\"facts_path\": \"config[0].meaning.id\", \"text\": \"…\"}]")
    p = sub.add_parser("briefs")
    p.add_argument("--repo", default=".")
    p.add_argument("--app-state", required=True)
    p.add_argument("--flows", help="comma-separated flow ids (default: every important flow)")
    p = sub.add_parser("diagrams")
    p.add_argument("--repo", default=".")
    p.add_argument("--app", required=True)
    p.add_argument("--only", help="comma-separated spec name prefixes, e.g. a flow id")
    p.add_argument("--drawio", help="path to the draw.io CLI (default: found on PATH)")
    p = sub.add_parser("assemble")
    p.add_argument("--repo", default=".")
    p.add_argument("--app-state", required=True)
    p = sub.add_parser("check-fragment")
    p.add_argument("--repo", default=".")
    p.add_argument("--app-state", required=True)
    p.add_argument("--fragment-dir", required=True)
    p = sub.add_parser("usage-spend")
    p.add_argument("--repo", default=".")
    p.add_argument("--since", required=True, help="the run's start time, UTC, e.g. 2026-11-23T04:30:00Z")
    p = sub.add_parser("stamp")
    p.add_argument("--repo", default=".")
    p.add_argument("--app-state", required=True)
    p = sub.add_parser("render")
    p.add_argument("--repo", default=".")
    p.add_argument("--app-state", required=True)
    p.add_argument("--check", action="store_true", help="write nothing; exit 1 if a block is stale or missing")
    p.add_argument("--refresh-owners", action="store_true", help="take a new owners snapshot (once per run)")
    p = sub.add_parser("owners")
    p.add_argument("--repo", default=".")
    p.add_argument("--root", required=True, help="the app's folder, repo-relative ('.' for the repo root)")
    p = sub.add_parser("skill-pin")
    p.add_argument("--repo", default=".")
    p.add_argument("--name", required=True)
    p.add_argument("--dir", required=True)
    p = sub.add_parser("clip")
    p.add_argument("file")
    p.add_argument("--file-ref", action="store_true", help="copy the file itself (for image paste), not its text")
    p = sub.add_parser("svg-theme")
    p.add_argument("--repo", default=".")
    p.add_argument("--app")
    p.add_argument("--mode", choices=["adaptive", "light"])
    args = parser.parse_args()
    handlers = {"meta": cmd_meta, "detect": cmd_detect, "author": cmd_author, "drift": cmd_drift,
                "validate": cmd_validate, "svg-theme": cmd_svg_theme, "migrate": cmd_migrate, "readme-plan": cmd_readme_plan,
                "facts-snapshot": cmd_facts_snapshot, "facts-diff": cmd_facts_diff, "owners": cmd_owners,
                "render": cmd_render, "keep-snapshot": cmd_keep_snapshot, "keep-restore": cmd_keep_restore, "stamp": cmd_stamp, "check-fragment": cmd_check_fragment,
                "usage-spend": cmd_usage_spend, "readme": cmd_readme, "humanize-plan": cmd_humanize_plan, "facts-set": cmd_facts_set, "briefs": cmd_briefs, "diagrams": cmd_diagrams, "assemble": cmd_assemble,
                "upgrade-plan": cmd_upgrade_plan, "skill-pin": cmd_skill_pin, "clip": cmd_clip, "sync-plan": cmd_sync_plan, "sync-record": cmd_sync_record}
    try:
        handlers[args.cmd](args)
    except (RuntimeError, OSError, KeyError, ValueError) as exc:
        emit({"error": str(exc)}, 2)


if __name__ == "__main__":
    main()
