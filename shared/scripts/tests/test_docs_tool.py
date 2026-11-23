"""Tests for docs_tool.py. Each test builds a tiny git repo in a temp folder and runs the CLI.

    python3 -m unittest discover -s plugins/app-docs/shared/scripts/tests
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "docs_tool.py"
sys.path.insert(0, str(HERE.parent))
import docs_tool  # noqa: E402

REMOTE = "git@gitlab.example.com:team/shop.git"
WEB = "https://gitlab.example.com/team/shop"

HANDLER = textwrap.dedent("""\
    package handler

    func CreatePayment(w http.ResponseWriter, r *http.Request) {
        if r.Body == nil {
            log.Warn("invalid request")
            return
        }
        log.Info("payment created")
    }

    func Refund() {}
    """)


def run(repo, *args, code=None):
    proc = subprocess.run([sys.executable, str(TOOL), *args], cwd=repo, capture_output=True, text=True)
    if code is not None and proc.returncode != code:
        raise AssertionError("exit %d, wanted %d\n%s\n%s" % (proc.returncode, code, proc.stdout, proc.stderr))
    try:
        return proc.returncode, json.loads(proc.stdout)
    except ValueError:
        return proc.returncode, proc.stdout


class Repo:
    def __init__(self, remote=REMOTE):
        self.path = Path(tempfile.mkdtemp(prefix="docgen-test-"))
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Jane Doe")
        self.git("config", "user.email", "jane@example.com")
        if remote:
            self.git("remote", "add", "origin", remote)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.path), *args], check=True, capture_output=True, text=True).stdout.strip()

    def write(self, rel, text):
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self, message="change"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def cleanup(self):
        shutil.rmtree(self.path, ignore_errors=True)


def documented_repo(template_version=3, dev_body=None, op_body=None, extra_op_sections=True):
    """A repo with one documented app, 'pay', whose docs follow the current conventions."""
    repo = Repo()
    repo.write("pay/handler.go", HANDLER)
    sha = repo.commit("code")
    link = "[`pay/handler.go:3-9`](%s/-/blob/%s/pay/handler.go#L3-9)" % (WEB, sha)
    sub = "> generated at `%s` on `main`, 2026-11-15, run by Jane Doe" % sha[:7]
    dev_sections = ["overview", "structure", "setup", "startup", "app-flow", "data-flow", "dev-notes", "glossary"]
    op_sections = ["setup", "how-it-works", "app-flow", "data-flow", "troubleshooting"]
    op_sections += (["log-index", "alerts", "owners"] if extra_op_sections else []) + ["glossary"]

    diagram = "```mermaid\nflowchart TD\n  a --> b\n  classDef x fill:#fff\n```"
    needs = {"structure": 1, "startup": 1, "data-flow": 1, "how-it-works": 2}

    def doc(title, ids, bodies):
        out = ["# Pay: %s" % title, ""]
        for sid in ids:
            out += ['<!-- docgen:section id="%s" -->' % sid, "## %s" % sid, sub, "", bodies.get(sid, "Text."), ""]
            out += [diagram, ""] * needs.get(sid, 0)
        return "\n".join(out)

    dev = {"overview": "`CreatePayment` handler (%s) validates the body." % link}
    dev.update(dev_body or {})
    op = {"log-index": "| Pesan | Level |\n|---|---|\n| `payment created` | INFO |\n"}
    op.update(op_body or {})
    repo.write("docs/pay/dev-guide.md", doc("Dev Guide", dev_sections, dev))
    repo.write("docs/pay/operator-guide.md", doc("User Guide", op_sections, op))
    sections = {"%s:%s" % (k, sid): {"sha": sha, "dirty": False, "files": ["pay/handler.go"], "status": "active"}
                for k, ids in (("dev", dev_sections), ("op", op_sections)) for sid in ids}
    app_state = {"app_id": "pay", "root": "pay", "fsm": False, "flows": [{"id": "create", "label": "POST /pay", "important": False}],
                 "docs": {"dev": "docs/pay/dev-guide.md", "operator": "docs/pay/operator-guide.md"}, "sections": sections}
    repo.write("docs/.docgen/apps/pay.json", json.dumps(app_state))
    repo.write("docs/.docgen/state.json", json.dumps({
        "template_version": template_version, "humanizer_version": docs_tool.HUMANIZER_VERSION,
        "diagram_version": docs_tool.DIAGRAM_VERSION, "story_version": docs_tool.STORY_VERSION,
        "apps": {"pay": {"root": "pay", "stage": "done"}}, "docmost": {}}))
    # the doc mentions the flow label so the validator's flow check passes
    with open(repo.path / "docs/pay/dev-guide.md", "a") as f:
        f.write("\nPOST /pay\n")
    with open(repo.path / "docs/pay/operator-guide.md", "a") as f:
        f.write("\nPOST /pay\n")
    repo.commit("docs")
    return repo, sha


def validate(repo):
    return run(repo.path, "validate", "--repo", str(repo.path), "--app-state", "docs/.docgen/apps/pay.json")[1]


def rules(result):
    return {f["rule"] for f in result["failures"]}


class RemoteAndLinks(unittest.TestCase):
    def test_web_url_forms(self):
        for remote in ("git@gitlab.example.com:team/shop.git", "ssh://git@gitlab.example.com:2222/team/shop.git",
                       "https://gitlab.example.com/team/shop.git", "https://ci:token@gitlab.example.com/team/shop"):
            repo = Repo(remote)
            try:
                self.assertEqual(docs_tool.web_url(str(repo.path)), WEB, remote)
            finally:
                repo.cleanup()

    def test_no_remote(self):
        repo = Repo(remote=None)
        try:
            self.assertIsNone(docs_tool.web_url(str(repo.path)))
        finally:
            repo.cleanup()

    def test_permalink(self):
        self.assertEqual(docs_tool.permalink(WEB, "abc", "a/b.go", 3, 9), WEB + "/-/blob/abc/a/b.go#L3-9")
        self.assertEqual(docs_tool.permalink(WEB, "abc", "a/b.go", 3), WEB + "/-/blob/abc/a/b.go#L3")

    def test_meta_reports_unpushed_head(self):
        repo = Repo()
        try:
            repo.write("a.txt", "x")
            repo.commit()
            meta = run(repo.path, "meta", "--repo", str(repo.path), code=0)[1]
            self.assertEqual(meta["web_url"], WEB)
            self.assertFalse(meta["head_pushed"])
        finally:
            repo.cleanup()


class Facts(unittest.TestCase):
    def test_units_compare_across_languages(self):
        self.assertEqual(docs_tool.section_facts("timeout 5 menit, retry after 30 detik"),
                         docs_tool.section_facts("timeout 5 minutes, retry after 30 seconds"))

    def test_code_links_are_not_facts(self):
        facts = docs_tool.section_facts("See [`a/b.go:1-2`](https://x/y) and `PAYMENT_TIMEOUT_MS`.")
        self.assertEqual(facts, {"PAYMENT_TIMEOUT_MS"})

    def test_facts_diff_strict_fails_on_change(self):
        repo, _ = documented_repo(op_body={"setup": "Timeout `PAYMENT_TIMEOUT_MS`, 30 detik."})
        try:
            snap = str(repo.path / "snap.json")
            run(repo.path, "facts-snapshot", "--repo", str(repo.path), "--app-state", "docs/.docgen/apps/pay.json", "--out", snap, code=0)
            guide = repo.path / "docs/pay/operator-guide.md"
            guide.write_text(guide.read_text().replace("30 detik", "setengah menit"))
            code, out = run(repo.path, "facts-diff", "--repo", str(repo.path), "--app-state", "docs/.docgen/apps/pay.json",
                            "--before", snap, "--only", "op", "--strict")
            self.assertEqual(code, 1)
            self.assertEqual(out["changes"][0]["lost"], ["30s"])
        finally:
            repo.cleanup()


class Validate(unittest.TestCase):
    def test_clean_docs_pass(self):
        repo, _ = documented_repo()
        try:
            result = validate(repo)
            self.assertEqual(result["failures"], [])
        finally:
            repo.cleanup()

    def test_plain_code_ref_must_be_a_link(self):
        repo, _ = documented_repo(dev_body={"structure": "Router at `pay/handler.go:3`."})
        try:
            self.assertIn("code-ref-not-linked", rules(validate(repo)))
        finally:
            repo.cleanup()

    def test_symbol_outside_cited_lines_warns(self):
        repo, sha = documented_repo()
        try:
            link = "[`pay/handler.go:3-9`](%s/-/blob/%s/pay/handler.go#L3-9)" % (WEB, sha)
            guide = repo.path / "docs/pay/dev-guide.md"
            guide.write_text(guide.read_text().replace("Text.", "`Refund()` is here (%s)." % link, 1))
            self.assertTrue(any("none of `Refund`" in w for w in validate(repo)["warnings"]))
        finally:
            repo.cleanup()

    def test_guides_disagreeing_on_a_fact_warn(self):
        repo, _ = documented_repo(dev_body={"setup": "Timeout is 5 minutes."}, op_body={"setup": "Timeout 10 menit."})
        try:
            self.assertTrue(any("fact-mismatch in 'setup'" in w and "10min" in w for w in validate(repo)["warnings"]))
        finally:
            repo.cleanup()

    def test_invented_log_message_fails(self):
        repo, _ = documented_repo(op_body={"log-index": "| Pesan | Level |\n|---|---|\n| `payment exploded <id>` | ERROR |\n"})
        try:
            self.assertIn("log-message-unknown", rules(validate(repo)))
        finally:
            repo.cleanup()

    def test_old_template_doesnt_require_new_sections(self):
        repo, _ = documented_repo(template_version=2, extra_op_sections=False)
        try:
            self.assertNotIn("section-missing", rules(validate(repo)))
        finally:
            repo.cleanup()

    def test_current_template_requires_new_sections(self):
        repo, _ = documented_repo(template_version=3, extra_op_sections=False)
        try:
            self.assertIn("section-missing", rules(validate(repo)))
        finally:
            repo.cleanup()


class Migrate(unittest.TestCase):
    def test_old_subtitles_and_plain_refs(self):
        repo, sha = documented_repo()
        try:
            guide = repo.path / "docs/pay/dev-guide.md"
            text = guide.read_text()
            text = text.replace("> generated at `%s` on `main`, 2026-11-15, run by Jane Doe" % sha[:7],
                                "> `%s` · `main` · 2026-11-15 · verified by Jane Doe" % sha[:7])
            text = text.replace("Text.", "Router at `pay/handler.go:3-4`.", 1)
            guide.write_text(text)
            out = run(repo.path, "migrate", "--repo", str(repo.path), code=0)[1]
            self.assertGreater(out["subtitles"], 0)
            self.assertEqual(out["links"], 1)
            new = guide.read_text()
            self.assertNotIn("verified by", new)
            self.assertIn("[`pay/handler.go:3-4`](%s/-/blob/%s/pay/handler.go#L3-4)" % (WEB, sha), new)
            self.assertEqual(run(repo.path, "migrate", "--repo", str(repo.path))[1]["links"], 0, "idempotent")
        finally:
            repo.cleanup()

    def test_page_keys_move_to_structure_keys(self):
        repo, _ = documented_repo()
        try:
            state_file = repo.path / "docs/.docgen/state.json"
            state = json.loads(state_file.read_text())
            state["docmost"] = {"pages": {"pay": {"url": "u0"}, "pay/operator-guide.md": {"url": "u1"}, "pay/dev-guide.md": {"url": "u2"}}}
            state_file.write_text(json.dumps(state))
            run(repo.path, "migrate", "--repo", str(repo.path), code=0)
            pages = json.loads(state_file.read_text())["docmost"]["pages"]
            self.assertEqual(pages, {"pay": {"url": "u0"}, "pay/op": {"url": "u1"}, "pay/dev": {"url": "u2"}})
            plan = run(repo.path, "sync-plan", "--repo", str(repo.path), code=0)[1]
            self.assertEqual({p["key"]: p["existing_url"] for p in plan["pages"]}, {"pay": "u0", "pay/op": "u1", "pay/dev": "u2"})
            self.assertEqual(plan["orphans"], [])
        finally:
            repo.cleanup()


class Sync(unittest.TestCase):
    def test_orphans_and_remove_key(self):
        repo, _ = documented_repo()
        try:
            state_file = repo.path / "docs/.docgen/state.json"
            state = json.loads(state_file.read_text())
            state["docmost"] = {"pages": {"gone-app": {"url": "u9"}}}
            state_file.write_text(json.dumps(state))
            plan = run(repo.path, "sync-plan", "--repo", str(repo.path), code=0)[1]
            self.assertEqual(plan["orphans"], [{"key": "gone-app", "url": "u9"}])
            run(repo.path, "sync-record", "--repo", str(repo.path), "--remove-key", "gone-app", code=0)
            self.assertEqual(run(repo.path, "sync-plan", "--repo", str(repo.path))[1]["orphans"], [])
        finally:
            repo.cleanup()

    def test_prepared_files_exist(self):
        repo, _ = documented_repo()
        try:
            page = next(p for p in run(repo.path, "sync-plan", "--repo", str(repo.path))[1]["pages"] if p["key"] == "pay/op")
            for name in ("prepared_file", "prepare_js", "check_js", "paste_js"):
                self.assertTrue(Path(page[name]).is_file(), name)
            self.assertNotIn("docgen:section", Path(page["prepared_file"]).read_text())
        finally:
            repo.cleanup()


class Owners(unittest.TestCase):
    def test_match_rules(self):
        m = docs_tool._codeowner_match
        self.assertTrue(m("/services/pay/", "/services/pay/"))
        self.assertFalse(m("/services/pay", "/services/pay-v2/"))
        self.assertTrue(m("services/", "/apps/services/x/"))
        self.assertTrue(m("/services/*", "/services/pay/"))
        self.assertTrue(m("*", "/anything/"))

    def test_sections_add_up_and_last_match_wins(self):
        repo = Repo()
        try:
            repo.write("pay/x.go", "package x\n")
            repo.write("CODEOWNERS", "* @everyone\n/pay/ @team-pay\n[Database] @dba\n/pay/ \n")
            repo.write(".gitlab/CODEOWNERS", "* @ignored\n")
            repo.commit()
            out = run(repo.path, "owners", "--repo", str(repo.path), "--root", "pay", code=0)[1]
            self.assertEqual(out["owners"], ["@team-pay", "@dba"])
            self.assertEqual(out["escalation"], out["owners"])
            self.assertEqual(out["source"], "CODEOWNERS")
        finally:
            repo.cleanup()

    def test_committers_when_no_codeowners(self):
        repo = Repo()
        try:
            repo.write("pay/x.go", "package x\n")
            repo.commit()
            out = run(repo.path, "owners", "--repo", str(repo.path), "--root", "pay", code=0)[1]
            self.assertEqual(out["owners"], ["Jane Doe <jane@example.com>"])
            self.assertIsNone(out["escalation"])
        finally:
            repo.cleanup()


class Upgrades(unittest.TestCase):
    def test_two_to_three_only_adds_sections(self):
        repo, _ = documented_repo(template_version=2, extra_op_sections=False)
        try:
            plan = run(repo.path, "upgrade-plan", "--repo", str(repo.path), code=0)[1]
            self.assertEqual([p["action"] for p in plan["pending"]], ["extend", "facts"])
            self.assertEqual(plan["pending"][0]["sections"]["op"], ["log-index", "alerts", "owners"])
            drift = run(repo.path, "drift", "--repo", str(repo.path))[1]
            self.assertFalse(drift["template_changed"])
        finally:
            repo.cleanup()

    def test_up_to_date_has_nothing_pending(self):
        repo, _ = documented_repo(template_version=docs_tool.TEMPLATE_VERSION)
        try:
            self.assertEqual(run(repo.path, "upgrade-plan", "--repo", str(repo.path), code=0)[1]["pending"], [])
        finally:
            repo.cleanup()

    def test_skill_pin_reports_change(self):
        repo, _ = documented_repo()
        skill = Path(tempfile.mkdtemp())
        try:
            (skill / "SKILL.md").write_text("v1")
            first = run(repo.path, "skill-pin", "--repo", str(repo.path), "--name", "h", "--dir", str(skill), code=0)[1]
            self.assertFalse(first["changed"])
            (skill / "SKILL.md").write_text("v2")
            self.assertTrue(run(repo.path, "skill-pin", "--repo", str(repo.path), "--name", "h", "--dir", str(skill))[1]["changed"])
        finally:
            repo.cleanup()
            shutil.rmtree(skill, ignore_errors=True)


class Usage(unittest.TestCase):
    def test_record_and_compare_runs(self):
        repo, _ = documented_repo()
        try:
            def record(run_id, stage, agent, *extra):
                subprocess.run([sys.executable, str(TOOL), "usage-record", "--repo", str(repo.path), "--run", run_id,
                                "--app", "pay", "--stage", stage, "--agent", agent, *extra], check=True, capture_output=True)
            record("2026-11-20T01:00:00Z", "draft", "app-documenter", "--tokens", "900")
            record("2026-11-22T01:00:00Z", "draft", "app-documenter", "--tokens", "500", "--ms", "1000")
            record("2026-11-22T01:00:00Z", "review", "goldfish-reviewer")
            report = run(repo.path, "usage-report", "--repo", str(repo.path), code=0)[1]
            self.assertEqual(report["current"]["total_tokens"], 500)
            self.assertEqual(report["current"]["apps"]["pay"]["review"]["unknown"], 1)
            self.assertEqual(report["previous"]["total_tokens"], 900)
        finally:
            repo.cleanup()


def v4_repo(split=False):
    """A template-4 repo: render markers in both guides, a facts file, one important flow still as a placeholder."""
    repo = Repo()
    repo.write("pay/handler.go", HANDLER)
    sha = repo.commit("code")
    sub = "> generated at `%s` on `main`, 2026-11-15, run by Jane Doe" % sha[:7]

    def blk(i):
        return '<!-- docgen:render id="%s" -->\n<!-- /docgen:render -->' % i

    def section(sid, body):
        return '<!-- docgen:section id="%s" -->\n## %s\n%s\n\n%s\n' % (sid, sid, sub, body)
    dev = "# Pay: Dev Guide\n\n" + "\n".join([
        section("overview", "Pay takes payments ([`pay/handler.go:3-9`](%s/-/blob/%s/pay/handler.go#L3-9)). It calls the wallet.\n\n| | |\n|---|---|\n| Type | backend API |\n| Entry point | x |" % (WEB, sha)),
        section("setup", "### Configuration\n%s\n\n### Run\n```bash\ngo run ./cmd/server\n```" % blk("config")),
        section("app-flow", blk("flow-index") + '\n\n<!-- docgen:flow id="create" -->'),
        section("data-flow", blk("storage")),
        section("dev-notes", "\n\n".join(blk("notes:" + n) for n in ("gotchas", "unverified", "contradictions", "security", "tech-debt"))),
        section("glossary", blk("glossary"))])
    op = "# Pay: User Guide\n\n" + "\n".join([
        section("setup", "Selain itu, aplikasi ini merupakan layanan pembayaran.\n\n" + blk("config")),
        section("app-flow", blk("flow-index") + '\n\n<!-- docgen:flow id="create" -->'),
        section("data-flow", blk("storage")),
        section("troubleshooting", blk("common-errors") + "\n\n" + blk("config-effects")),
        section("log-index", blk("log-index")),
        section("alerts", blk("metrics") + "\n\n" + blk("alerts")),
        section("owners", blk("owners")),
        section("glossary", blk("glossary"))])
    repo.write("docs/pay/dev-guide.md", dev)
    repo.write("docs/pay/operator-guide.md", op)
    repo.write("docs/.docgen/facts/pay.json", json.dumps({
        "config": [{"key": "WALLET_URL", "required": True, "example": "<https://wallet.example.com>",
                    "meaning": {"en": "Wallet base URL", "id": "Alamat wallet"}, "if_wrong": {"id": "Redeem gagal 502"}}],
        "flows": {"create": {"purpose": {"en": "Create a payment", "id": "Membuat pembayaran"}}},
        "storage": [{"name": "vouchers.json", "kind": "file", "where": "DATA_DIR", "data": {"en": "All vouchers", "id": "Semua voucher"}}],
        "logs": [{"message": "payment created", "level": "INFO"}],
        "glossary": [{"term": "Voucher", "en": "A code worth money", "id": "Kode bernilai uang"}]}))
    app_state = {"app_id": "pay", "root": "pay", "fsm": False, "split": split,
                 "flows": [{"id": "create", "label": "POST /pay", "important": True, "entry": "pay/handler.go:3"}],
                 "docs": {"dev": "docs/pay/dev-guide.md", "operator": "docs/pay/operator-guide.md"},
                 "sections": {"dev:overview": {"sha": sha, "date": "2026-11-15", "branch": "main"}}}
    repo.write("docs/.docgen/apps/pay.json", json.dumps(app_state))
    repo.write("docs/.docgen/state.json", json.dumps({"template_version": 4, "humanizer_version": docs_tool.HUMANIZER_VERSION,
                                                      "diagram_version": docs_tool.DIAGRAM_VERSION, "story_version": docs_tool.STORY_VERSION,
                                                      "apps": {"pay": {"root": "pay", "stage": "done"}}, "docmost": {}}))
    repo.commit("docs")
    fragment = repo.path / "docs/.docgen/.work/fragments/pay/create"
    fragment.mkdir(parents=True)
    (fragment / "dev.md").write_text('<!-- docgen:section id="app-flow/create" -->\n### 5.1 Create\n%s\n\n![Create: flowchart](diagrams/create.flow.drawio.svg)\n\n%s\n\n%s\n'
                                     % (sub, blk("errors:create"), blk("side-effects:create")))
    (fragment / "op.md").write_text('<!-- docgen:section id="app-flow/create" -->\n### 3.1 Membuat\n%s\n\nData diperiksa. Dengan demikian, request yang mana kosong ditolak.\n\n%s\n'
                                    % (sub, blk("if-failed:create")))
    (fragment / "facts.json").write_text(json.dumps({
        "flow_details": {"create": {"errors": [{"when": {"en": "body missing", "id": "body kosong"}, "caller_gets": "`400`", "ref": "pay/handler.go:4-6",
                                                "cause": {"id": "Caller tidak mengirim body."}, "check": {"id": "Periksa request."}}], "side_effects": []}},
        "logs": [{"message": "invalid request", "level": "WARN"}]}))
    (fragment / "state.json").write_text(json.dumps({"sections": {"dev:app-flow/create": {"sha": sha}, "op:app-flow/create": {"sha": sha}}}))
    return repo, sha


class Rendering(unittest.TestCase):
    def setUp(self):
        self.repo, self.sha = v4_repo()
        self.state = str(self.repo.path / "docs/.docgen/apps/pay.json")

    def tearDown(self):
        self.repo.cleanup()

    def tool(self, *args, code=None):
        return run(self.repo.path, *args, "--repo", str(self.repo.path), code=code)[1]

    def test_assemble_places_flow_merges_facts_and_renders(self):
        out = self.tool("assemble", "--app-state", self.state, code=0)
        self.assertEqual(out["assembled"], ["create"])
        dev = (self.repo.path / "docs/pay/dev-guide.md").read_text()
        self.assertNotIn("docgen:flow", dev)
        self.assertIn("- body missing → `400` ([`pay/handler.go:4-6`](%s/-/blob/%s/pay/handler.go#L4-6))" % (WEB, self.sha), dev)
        op = (self.repo.path / "docs/pay/operator-guide.md").read_text()
        self.assertIn("- body kosong: Caller tidak mengirim body. Periksa request.", op)
        self.assertIn("| `invalid request` | WARN |", op, "flow logs merged into the log index")
        self.assertIn("| `payment created` | INFO |", op, "app-level logs kept")
        self.assertIn("| Pemilik | Jane Doe <jane@example.com> |", op)
        self.assertIn("op:app-flow/create", json.loads(Path(self.state).read_text())["sections"])
        self.assertFalse((self.repo.path / "docs/.docgen/.work/fragments/pay/create").exists())
        self.assertTrue(self.tool("render", "--app-state", self.state, "--check", code=0)["ok"])

    def test_assemble_replaces_an_existing_section(self):
        self.tool("assemble", "--app-state", self.state, code=0)
        fragment = self.repo.path / "docs/.docgen/.work/fragments/pay/create"
        fragment.mkdir(parents=True)
        (fragment / "dev.md").write_text('<!-- docgen:section id="app-flow/create" -->\n### 5.1 Create v2\n> x\n\nnew text\n')
        (fragment / "op.md").write_text('<!-- docgen:section id="app-flow/create" -->\n### 3.1 Membuat v2\n> x\n\nteks baru\n')
        self.tool("assemble", "--app-state", self.state, code=0)
        dev = (self.repo.path / "docs/pay/dev-guide.md").read_text()
        self.assertEqual(dev.count('id="app-flow/create"'), 1)
        self.assertIn("new text", dev)
        self.assertIn('<!-- docgen:section id="data-flow" -->', dev, "the next section survives")

    def test_hand_edited_table_is_stale(self):
        self.tool("assemble", "--app-state", self.state, code=0)
        guide = self.repo.path / "docs/pay/operator-guide.md"
        guide.write_text(guide.read_text().replace("Alamat wallet", "Alamat wallet (diubah)"))
        code, out = run(self.repo.path, "render", "--repo", str(self.repo.path), "--app-state", self.state, "--check")
        self.assertEqual(code, 1)
        self.assertTrue(any("config" in c for c in out["changed"]))

    def test_split_mode_writes_flow_files_with_fixed_image_paths(self):
        self.repo.cleanup()
        self.repo, self.sha = v4_repo(split=True)
        self.state = str(self.repo.path / "docs/.docgen/apps/pay.json")
        state = json.loads(Path(self.state).read_text())
        for kind, folder in (("dev", "dev"), ("operator", "operator")):
            (self.repo.path / "docs/pay" / folder).mkdir(parents=True)
            state["docs"][kind] = "docs/pay/%s" % folder
        Path(self.state).write_text(json.dumps(state))
        self.tool("assemble", "--app-state", self.state)
        flow_file = self.repo.path / "docs/pay/dev/05-app-flow/01-create.md"
        self.assertTrue(flow_file.is_file())
        self.assertIn("](../../diagrams/create.flow.drawio.svg)", flow_file.read_text())

    def test_sync_drops_render_markers(self):
        self.tool("assemble", "--app-state", self.state, code=0)
        page = next(p for p in self.tool("sync-plan")["pages"] if p["key"] == "pay/op")
        text = Path(page["prepared_file"]).read_text()
        self.assertNotIn("docgen:", text)
        self.assertIn("| `WALLET_URL` |", text)

    def test_briefs(self):
        out = self.tool("briefs", "--app-state", self.state, code=0)
        brief = json.loads((self.repo.path / out["briefs"][0]).read_text())
        self.assertEqual(brief["numbers"]["dev"], "5.1")
        self.assertEqual(brief["terms"], ["Voucher"])

    def test_humanize_plan_picks_only_paragraphs_with_tells(self):
        self.tool("assemble", "--app-state", self.state, code=0)
        out = self.tool("humanize-plan", "--app-state", self.state, "--skill", "none", code=0)
        plan = json.loads((self.repo.path / out["plan"]).read_text())["paragraphs"]
        self.assertEqual(len(plan), 2)
        self.assertIn("merupakan", plan[0]["reasons"])
        self.assertIn("relative-pronoun calque", plan[1]["reasons"])
        self.assertTrue(all("docgen:render" not in p["text"] and "|" not in p["text"] for p in plan))

    def test_readme_is_rendered_without_code_refs(self):
        self.tool("assemble", "--app-state", self.state, code=0)
        out = self.tool("readme", code=0)
        self.assertIn("pay/README.md", out["written"])
        readme = (self.repo.path / "pay/README.md").read_text()
        self.assertIn("Pay takes payments. It calls the wallet.", readme)
        self.assertIn("go run ./cmd/server", readme)
        self.assertNotIn("handler.go", readme)
        self.assertNotIn("Entry point", readme)
        self.assertIn("| `POST /pay` | Create a payment |", readme)

    def test_diagrams_without_drawio_flags_everything(self):
        specs = self.repo.path / "docs/.docgen/.work/specs/pay"
        specs.mkdir(parents=True)
        shutil.copy(HERE.parent.parent / "references/spec-examples/inquiry.flow.json", specs / "create.flow.json")
        out = self.tool("diagrams", "--app", "pay", "--drawio", "/nonexistent/drawio")
        self.assertEqual(out["diagrams"], 1)
        self.assertEqual(len(out["flagged"]), 1)

    def test_diagrams_with_drawio_flags_only_problems(self):
        if not shutil.which("dot"):
            self.skipTest("Graphviz not installed")
        specs = self.repo.path / "docs/.docgen/.work/specs/pay"
        specs.mkdir(parents=True)
        shutil.copy(HERE.parent.parent / "references/spec-examples/inquiry.flow.json", specs / "create.flow.json")
        fake = self.repo.path / "fake-drawio"
        fake.write_text("#!/bin/sh\nwhile [ $# -gt 1 ]; do [ \"$1\" = -o ] && out=$2; shift; done\necho svg > \"$out\"\n")
        fake.chmod(0o755)
        out = self.tool("diagrams", "--app", "pay", "--drawio", str(fake), code=0)
        self.assertEqual(out["flagged"], [])
        self.assertEqual(out["exported"], 1)
        self.assertTrue((self.repo.path / "docs/pay/diagrams/create.flow.drawio.svg").is_file())


if __name__ == "__main__":
    unittest.main()
