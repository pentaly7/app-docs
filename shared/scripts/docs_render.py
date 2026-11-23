"""Tables and lists rendered from an app's facts file, so each fact is written once, by an agent, as
data, and both guides show it the same way. Prose (stories, how-it-works, steps) stays model-written.

A rendered block sits between two markers in a guide:

    <!-- docgen:render id="config" -->
    …generated, never edited by hand…
    <!-- /docgen:render -->

Facts format: references/facts-schema.md. Used by docs_tool.py (render, validate, assemble).
"""
import json
import os
import re
from pathlib import Path

import docs_tool as dt

BLOCK_RE = re.compile(r'^<!--\s*docgen:render\s+id="([^"]+)"\s*-->\s*$')
END_RE = re.compile(r"^<!--\s*/docgen:render\s*-->\s*$")
MARK_RE = re.compile(r"^>\s*(?:⚠️|🔒)\s*\*\*(Unverified|Contradiction|Security finding):\*\*\s*(.+)$")

UNKNOWN = {"dev": "_Unknown — not in this repository. Fill in manually._",
           "op": "_Belum diketahui: tidak ada di repository ini. Mohon diisi manual._"}
# Rendered blocks are regenerated, so their placeholder says where a person fills the value in.
UNKNOWN_AT = {"dev": "_Unknown — not in this repository. Fill it in at `%s` → `manual.%s`._",
              "op": "_Belum diketahui: tidak ada di repository ini. Isi di `%s` → `manual.%s`._"}
NONE = {"dev": "_None._", "op": "_Tidak ada._"}

# Block ids each guide must contain (template version 4). Per-flow blocks are checked per important flow.
REQUIRED = {
    "dev": ["config", "flow-index", "storage", "notes:gotchas", "notes:unverified", "notes:contradictions",
            "notes:security", "notes:tech-debt", "glossary"],
    "op": ["config", "flow-index", "storage", "config-effects", "common-errors", "log-index", "metrics",
           "alerts", "owners", "glossary"],
}
PER_FLOW = {"dev": ["errors", "side-effects"], "op": ["if-failed"]}


def facts_path(repo, app_id):
    return Path(repo) / dt.DOCS_DIR / ".docgen" / "facts" / ("%s.json" % app_id)


def load_facts(repo, app_id):
    path = facts_path(repo, app_id)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


class Context:
    """What a block needs besides the facts: the language, links and owners."""

    def __init__(self, repo, app_state, kind):
        self.repo = Path(repo)
        self.app_state = app_state
        self.kind = kind                      # "dev" or "op"
        self.lang = "en" if kind == "dev" else "id"
        self.base = dt.web_url(self.repo)
        self.head = dt.git(self.repo, "rev-parse", "HEAD", check=False).strip()
        known = sorted((sec.get("date", ""), sec["sha"]) for sec in app_state.get("sections", {}).values() if sec.get("sha"))
        self.fallback_sha = known[-1][1] if known else self.head
        self._owners = None

    def text(self, value):
        """A bilingual field ({"en": …, "id": …}) in this guide's language; plain strings pass through."""
        if isinstance(value, dict):
            return (value.get(self.lang) or "").strip()
        return (value or "").strip() if isinstance(value, str) else ""

    def ref(self, ref, section):
        """`path:10-20` as a permalink pinned to the section's commit (Dev Guide only)."""
        if not ref or self.kind != "dev":
            return ""
        match = re.match(r"^([^:\s]+):(\d+)(?:-(\d+))?$", ref.strip())
        if not match:
            return "`%s`" % ref
        span = "`%s`" % ref.strip()
        # never HEAD for a recorded app: links must not change just because a commit landed
        sha = self.app_state.get("sections", {}).get("dev:%s" % section, {}).get("sha") or self.fallback_sha
        if not self.base or not sha:
            return span
        end = int(match.group(3)) if match.group(3) else None
        return "[%s](%s)" % (span, dt.permalink(self.base, sha, match.group(1), int(match.group(2)), end))

    def unknown(self, field):
        rel = facts_path(".", self.app_state.get("app_id", "<app>")).as_posix().lstrip("./")
        return UNKNOWN_AT[self.kind] % (rel, field)

    def owners(self, facts=None, refresh=False):
        """Manual override first, then the snapshot taken at the last run, then CODEOWNERS / git now."""
        manual = (facts or {}).get("manual", {})
        snap = (facts or {}).get("owners_snapshot")
        if manual.get("owners") or manual.get("escalation"):
            base = snap or self._live_owners()
            return {"owners": manual.get("owners") or base["owners"], "escalation": manual.get("escalation") or base["escalation"],
                    "source": "manual", "escalation_source": "manual" if manual.get("escalation") else base.get("source")}
        if snap and not refresh:
            return snap
        return self._live_owners()

    def _live_owners(self):
        if self._owners is None:
            root = self.app_state.get("root", ".")
            found = dt._codeowners(self.repo, root)
            if found:
                self._owners = {"owners": found["owners"], "escalation": found["owners"], "source": found["source"]}
            else:
                committers = dt._top_committers(self.repo, root)
                self._owners = {"owners": [c["who"] for c in committers["owners"]] if committers else [],
                                "escalation": None, "source": "git" if committers else None}
        return self._owners


def _cell(text):
    return (text or "").replace("|", "\\|").replace("\n", " ").strip() or "-"


def _table(header, rows, empty):
    if not rows:
        return [empty]
    out = ["| %s |" % " | ".join(header), "|%s|" % "|".join("---" for _ in header)]
    out += ["| %s |" % " | ".join(_cell(c) for c in row) for row in rows]
    return out


def _code(value):
    value = (value or "").strip()
    return "`%s`" % value if value and not value.startswith("`") else value


def render_block(block_id, facts, ctx, section):
    """Lines for one block. Raises KeyError for an unknown block id."""
    dev = ctx.kind == "dev"
    t = ctx.text
    none, unknown = NONE[ctx.kind], UNKNOWN[ctx.kind]
    name, _, flow = block_id.partition(":")

    if block_id == "config":
        rows = []
        for c in facts.get("config", []):
            value = c.get("example") or ("default `%s`" % c["default"] if c.get("default") not in (None, "") else "")
            required = ("yes" if dev else "ya") if c.get("required") else ("no" if dev else "tidak")
            rows.append([_code(c.get("key")), required, t(c.get("meaning")), value if value.startswith(("`", "default")) else _code(value)])
        header = ["Key", "Required", "Meaning", "Example / default"] if dev else ["Key", "Wajib", "Fungsi", "Contoh / default"]
        lines = _table(header, rows, none)
        if dev and facts.get("config_loaded_at"):
            lines += ["", "Where config is loaded: %s." % ctx.ref(facts["config_loaded_at"], section)]
        return lines

    if block_id == "config-effects":
        rows = [[_code(c.get("key")), t(c.get("if_changed")), t(c.get("if_wrong"))]
                for c in facts.get("config", []) if t(c.get("if_changed")) or t(c.get("if_wrong"))]
        return _table(["Key", "Jika diubah", "Gejala jika salah"], rows, none)

    if block_id == "flow-index":
        details = facts.get("flows", {})
        rows = []
        for f in ctx.app_state.get("flows", []):
            if f.get("status") == "removed":
                continue
            d = details.get(f["id"], {})
            third = ctx.ref(f.get("entry"), section) if dev else t(d.get("check"))
            rows.append([_code(f.get("label")), t(d.get("purpose")), third])
        header = ["Flow", "Purpose", "Code"] if dev else ["Flow", "Fungsi", "Jika gagal, periksa"]
        return _table(header, rows, none)

    if block_id == "storage":
        rows = []
        for s in facts.get("storage", []):
            row = [_code(s.get("name")), s.get("kind", ""), s.get("where", ""), t(s.get("data")),
                   ", ".join(s.get("flows", [])), t(s.get("retention"))]
            rows.append(row)
        header = (["Name", "Storage type", "Where", "What is stored", "Flows", "Retention"] if dev else
                  ["Nama", "Jenis penyimpanan", "Lokasi", "Isi", "Flow", "Lama penyimpanan"])
        return _table(header, rows, none)

    if block_id == "common-errors":
        rows = [[_code(e.get("symptom")) if isinstance(e.get("symptom"), str) else t(e.get("symptom")), t(e.get("meaning")), t(e.get("check"))]
                for e in facts.get("common_errors", [])]
        return _table(["Pesan / gejala", "Artinya", "Yang diperiksa"], rows, none)

    if block_id == "log-index":
        rows = [[_code(l.get("message")), l.get("level", ""), t(l.get("when")), t(l.get("meaning"))]
                for l in facts.get("logs", [])]
        return _table(["Pesan", "Level", "Muncul saat", "Artinya dan yang diperiksa"], rows, none)

    if block_id == "metrics":
        rows = [[_code(m.get("name")), m.get("type", ""), t(m.get("meaning"))] for m in facts.get("metrics", [])]
        return _table(["Metric", "Jenis", "Arti"], rows, "Aplikasi ini tidak mengekspos metric.")

    if block_id == "alerts":
        alerts = facts.get("alerts", []) + facts.get("manual", {}).get("alerts", [])
        rows = [[_code(a.get("name")), t(a.get("when")), a.get("severity", ""), t(a.get("first_step"))] for a in alerts]
        lines = _table(["Alert", "Menyala jika", "Severity", "Langkah pertama"], rows, ctx.unknown("alerts"))
        sources = sorted({a["source"] for a in alerts if a.get("source")})
        if sources:
            lines += ["", "Sumber: %s." % ", ".join("`%s`" % s for s in sources)]
        return lines

    if block_id == "owners":
        o = ctx.owners(facts)
        label = {"git": "riwayat commit 6 bulan terakhir", "manual": "diisi manual", None: "-"}
        source = label.get(o["source"], o["source"])
        esc_source = label.get(o.get("escalation_source", o["source"]), o.get("escalation_source", o["source"]))
        rows = [["Pemilik", ", ".join(o["owners"]) or ctx.unknown("owners"), source],
                ["Eskalasi", ", ".join(o["escalation"]) if o["escalation"] else ctx.unknown("escalation"), esc_source if o["escalation"] else "-"]]
        return _table(["Peran", "Siapa", "Sumber"], rows, unknown)

    if block_id == "glossary":
        rows = [[g.get("term", ""), g.get(ctx.lang, "")] for g in sorted(facts.get("glossary", []), key=lambda g: g.get("term", "").lower())]
        return _table(["Term", "Meaning in this app"] if dev else ["Istilah", "Arti"], rows, none)

    if name == "notes":
        if flow in ("unverified", "contradictions", "security"):
            return _marks_list(ctx, flow) or [none]
        key = {"gotchas": "gotchas", "tech-debt": "tech_debt"}[flow]
        items = facts.get("notes", {}).get(key, [])
        return ["- %s%s" % (t(n.get("text")), " (%s)" % ctx.ref(n["ref"], section) if n.get("ref") else "") for n in items] or [none]

    if name in ("errors", "side-effects", "if-failed") and flow:
        detail = facts.get("flow_details", {}).get(flow, {})
        if name == "errors":
            items = ["- %s → %s%s" % (t(e.get("when")), e.get("caller_gets") or e.get("status", ""),
                                       " (%s)" % ctx.ref(e["ref"], section) if e.get("ref") else "")
                     for e in detail.get("errors", [])]
            return (["**Errors:**", ""] + items) if items else ["**Errors:** none."]
        if name == "side-effects":
            items = ["- %s%s" % (t(e.get("text")), " (%s)" % ctx.ref(e["ref"], section) if e.get("ref") else "")
                     for e in detail.get("side_effects", [])]
            return (["**Side effects:**", ""] + items) if items else ["**Side effects:** none."]
        items = ["- %s: %s %s" % (t(e.get("when")) or e.get("status", ""), t(e.get("cause")), t(e.get("check")))
                 for e in detail.get("errors", []) if t(e.get("when"))]
        return (["**Jika gagal:**", ""] + [i.rstrip() for i in items]) if items else ["**Jika gagal:** tidak ada cabang error."]

    raise KeyError(block_id)


def _marks_list(ctx, which):
    """Dev notes lists of marks are collected from the marks in the Dev Guide itself, so they never drift."""
    label = {"unverified": "Unverified", "contradictions": "Contradiction", "security": "Security finding"}[which]
    out = []
    for doc in _docs(ctx.repo, ctx.app_state, "dev"):
        for i, line in enumerate(doc.lines):
            m = MARK_RE.match(line.strip())
            if m and m.group(1) == label:
                out.append("- `%s`: %s" % (doc.section_at(i), m.group(2).strip()))
    return out


def _docs(repo, app_state, kind):
    target = app_state.get("docs", {}).get("dev" if kind == "dev" else "operator", "")
    return [dt.Doc(p, repo) for p in dt._doc_files(Path(repo), target)]


def render_app(repo, app_state, check=False, refresh_owners=False):
    """Fill every block in both guides. With check, write nothing and report blocks that differ.
    refresh_owners takes a new owners snapshot (once per run), so renders don't drift as days pass."""
    repo = Path(repo)
    facts = load_facts(repo, app_state.get("app_id", ""))
    if refresh_owners and not check:
        snap = Context(repo, app_state, "op")._live_owners()
        if facts.get("owners_snapshot") != snap:
            facts["owners_snapshot"] = snap
            path = facts_path(repo, app_state.get("app_id", ""))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(facts, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    report = {"changed": [], "unknown_blocks": [], "missing_blocks": []}
    for kind in ("dev", "op"):
        ctx = Context(repo, app_state, kind)
        seen = set()
        for doc in _docs(repo, app_state, kind):
            out, i, changed = [], 0, False
            while i < len(doc.lines):
                line = doc.lines[i]
                start = BLOCK_RE.match(line.strip())
                if not start:
                    out.append(line)
                    i += 1
                    continue
                end = next((j for j in range(i + 1, len(doc.lines)) if END_RE.match(doc.lines[j].strip())), None)
                if end is None:
                    end = i  # unclosed marker: render and close it here
                block_id = start.group(1)
                seen.add(block_id)
                try:
                    body = render_block(block_id, facts, ctx, doc.section_at(i))
                except KeyError:
                    report["unknown_blocks"].append("%s: %s" % (doc.rel, block_id))
                    out.extend(doc.lines[i:end + 1])
                    i = end + 1
                    continue
                new = [line] + body + ["<!-- /docgen:render -->"]
                if new != doc.lines[i:end + 1]:
                    changed = True
                    report["changed"].append("%s: %s" % (doc.rel, block_id))
                out.extend(new)
                i = end + 1
            if changed and not check:
                doc.path.write_text("\n".join(out) + "\n", encoding="utf-8")
        wanted = list(REQUIRED[kind])
        for f in app_state.get("flows", []):
            if f.get("important") and f.get("status", "active") == "active":
                wanted += ["%s:%s" % (b, f["id"]) for b in PER_FLOW[kind]]
        report["missing_blocks"] += ["%s: %s" % (kind, b) for b in wanted if b not in seen]
    return report


SHARED_KEYS = (("logs", "message"), ("glossary", "term"), ("metrics", "name"), ("config", "key"), ("storage", "name"))


def merge_facts(base, fragment, flow_id=None):
    """Merge a flow agent's facts fragment into the app's facts. The flow's own details are replaced.
    Shared lists (logs, glossary, metrics, config, storage) are merged by key and remember which flows
    claim each entry (`_by`); an entry no flow claims anymore is dropped. Entries written by the app
    agent have no `_by` and are never dropped here."""
    out = json.loads(json.dumps(base))
    if flow_id and "flow_details" in fragment:
        out.setdefault("flow_details", {})[flow_id] = fragment["flow_details"].get(flow_id, fragment["flow_details"])
    for key, ident in SHARED_KEYS:
        if flow_id is None and key not in fragment:
            continue
        current = {}
        for item in out.get(key, []):
            if flow_id and flow_id in item.get("_by", []):
                item = dict(item, _by=[f for f in item["_by"] if f != flow_id])
                if not item["_by"] and not item.get("_app"):
                    continue                     # only this flow claimed it, and it no longer does
            current[item.get(ident)] = item
        for item in fragment.get(key, []):
            merged = {**current.get(item.get(ident), {}), **item}
            if flow_id:
                claimed = set(current.get(item.get(ident), {}).get("_by", []))
                if item.get(ident) in current and "_by" not in current[item.get(ident)]:
                    merged["_app"] = True        # the app agent wrote it first: keep it even if flows drop it
                merged["_by"] = sorted(claimed | {flow_id})
            current[item.get(ident)] = merged
        out[key] = list(current.values())
    for key in ("gotchas", "tech_debt"):
        items = fragment.get("notes", {}).get(key)
        if items is not None:
            kept = [n for n in out.get("notes", {}).get(key, []) if n.get("flow") != flow_id]
            out.setdefault("notes", {})[key] = kept + [dict(n, flow=flow_id) for n in items]
    if "flows" in fragment:
        out.setdefault("flows", {}).update(fragment["flows"])
    return out


# ---------------------------------------------------------------- README (no model)

REF_PAREN_RE = re.compile(r"\s*\((?:\[`[^`]+`\]\([^)\s]+\)(?:,\s*)?)+\)")


def _strip_refs(text):
    """README text has no code references: drop "(link, link)" groups, then any leftover link or span."""
    return dt.LINKED_REF_RE.sub("", REF_PAREN_RE.sub("", text))


def _section_body(doc_list, section_id):
    """A section's lines without its anchor, heading and subtitle."""
    for doc in doc_list:
        text = doc.section_text(section_id)
        if text is not None:
            lines = text.split("\n")[1:]
            while lines and (not lines[0].strip() or lines[0].startswith("#") or lines[0].startswith(">")):
                lines = lines[1:]
            return lines
    return []


def _first_paragraph(lines):
    para = []
    for line in lines:
        if not line.strip():
            if para:
                break
            continue
        if line.lstrip().startswith(("|", "!", "```", "<!--", "#")):
            if para:
                break
            continue
        para.append(line.strip())
    return " ".join(para)


def _kv_table(lines):
    rows = {}
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.lstrip().startswith("|") and len(cells) >= 2 and cells[0] and not set(cells[0]) <= set("-: "):
            rows[cells[0]] = cells[1]
    return rows


def _subsection(lines, title):
    out, inside = [], False
    for line in lines:
        if line.startswith("### "):
            inside = line[4:].strip().lower() == title.lower()
            continue
        if inside:
            out.append(line)
    return out


def _first_block(lines, lang_start=("```",)):
    out, inside = [], False
    for line in lines:
        if line.lstrip().startswith("```"):
            if inside:
                out.append(line)
                return out
            if line.strip().startswith(lang_start):
                inside = True
        if inside:
            out.append(line)
    return []


def app_readme(repo, entry, app_state):
    """The per-app README (readme-template.md), from the Dev Guide sections and the facts file."""
    repo = Path(repo)
    devs = _docs(repo, app_state, "dev")
    facts = load_facts(repo, entry["app_id"])
    ctx = Context(repo, app_state, "dev")
    ctx.base = None                                # README: no links into code
    overview = _section_body(devs, "overview")
    title = next((d.lines[0][2:].split(":")[0].split(" — ")[0].strip() for d in devs if d.lines and d.lines[0].startswith("# ")), entry["app_id"])
    stack = {k: _strip_refs(v) for k, v in _kv_table(overview).items() if k.lower() not in ("entry point",)}
    out = ["# %s" % title, "", _strip_refs(_first_paragraph(overview)), ""]
    if stack:
        out += ["## Tech stack", "| | |", "|---|---|"] + ["| %s | %s |" % (k, v) for k, v in stack.items()] + [""]
    run, fence = [], False
    for line in _subsection(_section_body(devs, "setup"), "Run"):
        fence = fence != line.lstrip().startswith("```")
        run.append(line if fence or line.lstrip().startswith("```") else _strip_refs(line))
    if any(l.strip() for l in run):
        out += ["## Quick start"] + run + [""]
    config = [l for l in render_block("config", facts, ctx, "setup") if not l.startswith("Where config is loaded")]
    out += ["## Configuration"] + [l for l in config if l.strip()] + [""]
    structure = _section_body(devs, "structure")
    out += ["## Structure"]
    if entry.get("structure_diagram"):
        out += ["![%s structure](%s)" % (title, entry["structure_diagram"]), ""]
    else:
        out += _first_block(structure, ("```mermaid",)) + [""]
    tree = [b for b in [_first_block([l for l in structure if not l.strip().startswith("```mermaid")])] if b]
    if tree and not tree[0][0].strip().startswith("```mermaid"):
        out += tree[0] + [""]
    rows = [[_code(f.get("label")), ctx.text(facts.get("flows", {}).get(f["id"], {}).get("purpose"))]
            for f in app_state.get("flows", []) if f.get("status") != "removed"]
    out += ["## Flows"] + _table(["Flow", "Purpose"], rows, NONE["dev"]) + [""]
    out += ["## Documentation",
            "- [Dev Guide](%s): how it works, with code references (English)" % entry["dev_guide"],
            "- [User Guide](%s): running and troubleshooting, for operators (Bahasa Indonesia)" % entry["user_guide"]]
    if entry.get("docmost_url"):
        out.append("- [Docmost](%s)" % entry["docmost_url"])
    out += ["", "## Owners", _owners_line(entry.get("owners")), ""] + _kept(repo / entry["readme"]) + ["---",
            "<sub>Docs generated from `%s` on `%s`, %s (the oldest section of the Dev Guide).</sub>"
            % ((entry.get("verified_sha") or "")[:7], entry.get("verified_branch") or "?", entry.get("verified_date") or "?")]
    corrected = [m for d in devs for m in (MARK_RE.match(l.strip()) for l in d.lines)
                 if m and m.group(1) == "Contradiction" and "README" in m.group(2)]
    return "\n".join(out).rstrip() + "\n", [c.group(2).strip() for c in corrected], {"title": title, "stack": stack,
                                                                                     "summary": _first_sentence(_strip_refs(_first_paragraph(overview)))}


def _kept(readme):
    """Keep blocks from the existing README, copied across unchanged (licence notes, badges, rules)."""
    if not readme.exists():
        return []
    lines = readme.read_text(encoding="utf-8").split("\n")
    out = []
    for start, end in dt._keep_blocks(lines):
        out += lines[start:end + 1] + [""]
    return out


def _first_sentence(text):
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    return match.group(1) if match else text


def _owners_line(owners):
    if not owners:
        return UNKNOWN["dev"]
    names = owners.get("owners", [])
    if owners.get("source", "").startswith("git"):
        return "Most active in the last 6 months: %s" % ", ".join("%s" % (o["who"] if isinstance(o, dict) else o) for o in names)
    return "%s (from `%s`)" % (", ".join(names), owners.get("source"))


def root_readme(repo, plan, infos):
    repo = Path(repo)
    name = (dt.web_url(repo) or repo.name).rstrip("/").split("/")[-1]
    rows = []
    for entry in plan["apps"]:
        info = infos.get(entry["app_id"], {})
        link = os.path.relpath(repo / entry["readme"], repo).replace(os.sep, "/")
        rows.append(["[%s](%s)" % (entry["app_id"], link), info.get("stack", {}).get("Type", ""),
                     info.get("stack", {}).get("Language & framework", ""), "`%s`" % entry["root"], info.get("summary", "")])
    out = ["# %s" % name, "", "This repository holds %d apps." % len(plan["apps"]), "", "## Apps"]
    out += _table(["App", "Type", "Stack", "Path", "What it does"], rows, NONE["dev"]) + [""]
    out += ["## Running everything", "See each app's Quick start in its README.", "", "## Documentation"]
    for entry in plan["apps"]:
        here = os.path.dirname(entry["readme"])
        docs = ["[Dev Guide](%s)" % os.path.normpath(os.path.join(here, entry["dev_guide"])).replace(os.sep, "/"),
                "[User Guide](%s)" % os.path.normpath(os.path.join(here, entry["user_guide"])).replace(os.sep, "/")]
        if entry.get("docmost_url"):
            docs.append("[Docmost](%s)" % entry["docmost_url"])
        out.append("- %s: %s" % (entry["app_id"], " · ".join(docs)))
    out += ["", "## Owners", _owners_line(plan["root_index"].get("owners")), ""] + _kept(repo / "README.md") + ["---",
            "<sub>Docs generated from: %s</sub>" % ", ".join("%s: `%s` (%s)" % (e["app_id"], (e.get("verified_sha") or "")[:7], e.get("verified_date"))
                                                         for e in plan["apps"])]
    return "\n".join(out) + "\n"
