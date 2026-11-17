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

Exit codes: 0 ok, 1 validation failures found, 2 usage/environment error.
"""
import argparse
import base64
import datetime
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

TEMPLATE_VERSION = 2
# Bumped when only the operator-guide humanizer rules change: re-humanize, don't regenerate.
HUMANIZER_VERSION = 2
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
    r"^> `[0-9a-f]{7,40}`( \+ uncommitted changes)? · `[^`]+` · \d{4}-\d{2}-\d{2} · verified by \S.*$"
)
CODE_REF_RE = re.compile(r"`([A-Za-z0-9_.@+/-]+\.([A-Za-z0-9]+)):(\d+)(?:-(\d+))?`")
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
DEV_ONLY_MARKS = ("**Unverified:**", "**Contradiction:**", "**Security finding:**")
REQUIRED_SECTIONS = {
    "dev": ["overview", "structure", "setup", "startup", "app-flow", "data-flow", "dev-notes", "glossary"],
    "op": ["setup", "how-it-works", "app-flow", "data-flow", "troubleshooting", "glossary"],
}
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
        "date": datetime.date.today().isoformat(),
        "user": git(repo, "config", "user.name", check=False).strip() or "unknown",
        "template_version": TEMPLATE_VERSION,
        "humanizer_version": HUMANIZER_VERSION,
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
        "template_changed": state.get("template_version") != TEMPLATE_VERSION,
        "humanizer_version_current": HUMANIZER_VERSION,
        "humanizer_changed": state.get("humanizer_version") != HUMANIZER_VERSION,
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
            if diff is None:
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
        found.append(("sequence" if ".seq." in name else "flowchart" if ".flow." in name else "other", image))
    for body in MERMAID_BLOCK_RE.findall(text):
        first = next((l.strip() for l in body.splitlines() if l.strip()), "")
        kind = "sequence" if first.startswith("sequenceDiagram") else "flowchart" if first.startswith(("flowchart", "graph")) else "other"
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
    if not re.search(r'background="#(?:fff|ffffff)"', xml, re.I):
        warnings.append("white page background not set")
    return failures, warnings



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

    for kind, doc_list in docs.items():
        prefix = "dev" if kind == "dev" else "op"
        if not doc_list:
            fail(app_state.get("docs", {}).get(kind, "?"), 0, "doc-missing", "%s doc not found" % kind)
            continue
        all_ids = {sid for d in doc_list for _, sid in d.anchors}
        for required in REQUIRED_SECTIONS[prefix]:
            if required not in all_ids:
                fail(doc_list[0].rel, 0, "section-missing", "required section '%s' has no anchor" % required)
        full_text = "\n".join("\n".join(d.lines) for d in doc_list)

        for flow in app_state.get("flows", []):
            if flow.get("label") and flow["label"] not in full_text:
                fail(doc_list[0].rel, 0, "flow-missing", "flow '%s' (%s) not mentioned" % (flow["id"], flow["label"]))
            if flow.get("important") and flow.get("status", "active") == "active":
                sid = "app-flow/%s" % flow["id"]
                text = next((d.section_text(sid) for d in doc_list if d.section_text(sid) is not None), None)
                if text is None:
                    fail(doc_list[0].rel, 0, "flow-section-missing", "important flow '%s' has no section" % flow["id"])
                    continue
                missing = {"flowchart", "sequence"} - {kind for kind, _ in _diagrams_in(text)}
                if missing:
                    fail(doc_list[0].rel, 0, "diagram-missing", "section '%s' has no %s" % (sid, " or ".join(sorted(missing))))

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
                    count = files.line_count(sha, path)
                    where = "working tree" if sha is None else sha[:7]
                    if count is None:
                        fail(doc.rel, i, "code-ref-file", "%s not found at %s" % (path, where))
                    elif start < 1 or end < start or end > count:
                        fail(doc.rel, i, "code-ref-lines", "%s:%d-%d outside file (%d lines at %s)" % (path, start, end, count, where))
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


# ---------------------------------------------------------------- sync

def _prepare_markdown(path):
    """Strip docgen anchors and the H1; swap drawio images for upload placeholders. Returns (text, [abs image paths])."""
    images = []
    out = []
    title_dropped = False
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if ANCHOR_RE.match(line.strip()):
            continue
        if not title_dropped and line.startswith("# "):
            title_dropped = True  # Docmost shows the page title separately
            continue

        def swap(match):
            image = (Path(path).parent / match.group(1)).resolve()
            images.append(str(image))
            return "[[diagram:%s]]" % image.name
        out.append(IMAGE_RE.sub(swap, line))
    return "\n".join(out).strip() + "\n", images


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


def cmd_sync_plan(args):
    repo = Path(args.repo).resolve()
    state = load_json(repo / DOCS_DIR / ".docgen" / "state.json")
    synced = state.get("docmost", {}).get("pages", {})
    work = repo / DOCS_DIR / ".docgen" / ".work" / "sync"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    pages = []

    def add(key, parent, title, source=None):
        entry = {"key": key, "parent": parent, "title": title, "existing_url": synced.get(key, {}).get("url")}
        if source:
            text, images = _prepare_markdown(source)
            digest = hashlib.sha256(text.encode())
            for image in images:
                digest.update(Path(image).read_bytes() if Path(image).is_file() else b"missing")
            name = key.replace("/", "__")
            prepared = work / (name if name.endswith(".md") else name + ".md")
            prepared.write_text(text, encoding="utf-8")
            paste_js = prepared.with_suffix(".paste.js")
            paste_js.write_text(_paste_js(title, text, images), encoding="utf-8")
            entry.update({"prepared_file": str(prepared), "paste_js": str(paste_js), "images": images,
                          "content_hash": "sha256:" + digest.hexdigest()})
            entry["changed"] = synced.get(key, {}).get("content_hash") != entry["content_hash"]
        else:
            entry["changed"] = entry["existing_url"] is None
        pages.append(entry)

    for app_id, app in sorted(state.get("apps", {}).items()):
        if app.get("stage") != "done":
            continue
        app_state = load_json(repo / DOCS_DIR / ".docgen" / "apps" / ("%s.json" % app_id))
        add(app_id, None, app_id)
        for kind, label in (("operator", "Operator Guide"), ("dev", "Dev Doc")):
            target = repo / app_state["docs"][kind]
            if target.is_file():
                add(target.relative_to(repo / DOCS_DIR).as_posix(), app_id, _title(target, label), target)
                continue
            container = "%s/%s" % (app_id, kind)
            add(container, app_id, label)

            def folder_page(folder):
                # A sub-folder's 00-index.md is that folder's page; its other files hang under it.
                if folder == target:
                    return container
                index = folder / "00-index.md"
                return index.relative_to(repo / DOCS_DIR).as_posix() if index.exists() else folder_page(folder.parent)

            for md in sorted(target.rglob("*.md")):
                is_index = md.name == "00-index.md" and md.parent != target
                parent = folder_page(md.parent.parent if is_index else md.parent)
                add(md.relative_to(repo / DOCS_DIR).as_posix(), parent, _title(md, md.stem), md)
    emit({"root_url": state.get("docmost", {}).get("root_url"),
          "method": state.get("docmost", {}).get("method"),
          "pages": pages,
          "to_sync": sum(1 for p in pages if p["changed"])})


def cmd_sync_record(args):
    repo = Path(args.repo).resolve()
    path = repo / DOCS_DIR / ".docgen" / "state.json"
    state = load_json(path)
    docmost = state.setdefault("docmost", {})
    if args.root_url:
        docmost["root_url"] = args.root_url
    if args.method:
        docmost["method"] = args.method
    if args.key:
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
    for name in ("meta", "detect", "drift", "sync-plan"):
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
    args = parser.parse_args()
    handlers = {"meta": cmd_meta, "detect": cmd_detect, "author": cmd_author, "drift": cmd_drift,
                "validate": cmd_validate, "sync-plan": cmd_sync_plan, "sync-record": cmd_sync_record}
    try:
        handlers[args.cmd](args)
    except (RuntimeError, OSError, KeyError, ValueError) as exc:
        emit({"error": str(exc)}, 2)


if __name__ == "__main__":
    main()
