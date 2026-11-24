"""Regression tests for the v2.10.0 review (bugs 2-14)."""
import json
import subprocess
import unittest
from pathlib import Path

from test_docs_tool import HANDLER, docs_tool, run, v4_repo


class ReviewFixes(unittest.TestCase):
    def setUp(self):
        self.repo, self.sha = v4_repo()
        self.state = str(self.repo.path / "docs/.docgen/apps/pay.json")

    def tearDown(self):
        self.repo.cleanup()

    def tool(self, *args, code=None):
        return run(self.repo.path, *args, "--repo", str(self.repo.path), code=code)[1]

    def test_fact_guard_sees_counts_limits_and_codes(self):
        before = docs_tool.section_facts("1. Mencoba ulang 3 kali, membalas 502, maksimal 100 transaksi.")
        for changed in ("1. Mencoba ulang 5 kali, membalas 502, maksimal 100 transaksi.",
                        "1. Mencoba ulang 3 kali, membalas 504, maksimal 100 transaksi.",
                        "1. Mencoba ulang 3 kali, membalas 502, maksimal 200 transaksi."):
            self.assertNotEqual(before, docs_tool.section_facts(changed), changed)
        self.assertEqual(docs_tool.section_facts("Dicoba ulang tiga kali."), docs_tool.section_facts("Dicoba ulang 3 kali."))
        self.assertNotIn("#1", before, "list numbers are structure, not facts")
        self.assertEqual(docs_tool.section_facts("### 5.1 Create\n> generated at `abc1234` on `main`, 2026-11-15, run by X"), set())

    def test_per_app_template_version(self):
        state_file = self.repo.path / "docs/.docgen/state.json"
        state = json.loads(state_file.read_text())
        state["template_version"] = 3
        state_file.write_text(json.dumps(state))
        app = json.loads(Path(self.state).read_text())
        app["template_version"] = 4               # converted early because it had drift
        Path(self.state).write_text(json.dumps(app))
        self.assertEqual(self.tool("upgrade-plan", code=0)["pending"], [], "a converted app isn't counted again")
        guide = self.repo.path / "docs/pay/operator-guide.md"
        guide.write_text(guide.read_text().replace('<!-- docgen:render id="owners" -->\n<!-- /docgen:render -->', ""))
        rules = {f["rule"] for f in self.tool("validate", "--app-state", self.state)["failures"]}
        self.assertIn("render-missing", rules, "render checks follow the app's own version")

    def test_renumbered_split_files_leave_no_stale_copy(self):
        self.repo.cleanup()
        self.repo, self.sha = v4_repo(split=True)
        self.state = str(self.repo.path / "docs/.docgen/apps/pay.json")
        state = json.loads(Path(self.state).read_text())
        for kind, folder in (("dev", "dev"), ("operator", "operator")):
            (self.repo.path / "docs/pay" / folder).mkdir(parents=True)
            state["docs"][kind] = "docs/pay/%s" % folder
        state["flows"].insert(0, {"id": "aaa", "label": "GET /a", "important": True})   # a new flow before it
        Path(self.state).write_text(json.dumps(state))
        stale = self.repo.path / "docs/pay/dev/05-app-flow/01-create.md"
        stale.parent.mkdir(parents=True)
        stale.write_text('<!-- docgen:section id="app-flow/create" -->\n### 5.1 Create\n> x\n\nold\n')
        self.tool("assemble", "--app-state", self.state)
        files = sorted(p.name for p in (self.repo.path / "docs/pay/dev/05-app-flow").glob("*.md"))
        self.assertEqual(files, ["02-create.md"])
        self.assertIn("### 5.2 Create", (self.repo.path / "docs/pay/dev/05-app-flow/02-create.md").read_text())

    def test_duplicate_anchors_fail(self):
        self.tool("assemble", "--app-state", self.state, code=0)
        guide = self.repo.path / "docs/pay/dev-guide.md"
        guide.write_text(guide.read_text() + '\n<!-- docgen:section id="glossary" -->\n## again\n')
        rules = {f["rule"] for f in self.tool("validate", "--app-state", self.state)["failures"]}
        self.assertIn("anchor-duplicate", rules)

    def test_shared_facts_drop_when_no_flow_claims_them(self):
        import docs_render
        base = {"logs": [{"message": "app start", "level": "INFO"}]}
        one = docs_render.merge_facts(base, {"logs": [{"message": "gone soon", "level": "WARN"}]}, "f1")
        self.assertEqual({l["message"] for l in one["logs"]}, {"app start", "gone soon"})
        two = docs_render.merge_facts(one, {"logs": []}, "f1")
        self.assertEqual({l["message"] for l in two["logs"]}, {"app start"})
        both = docs_render.merge_facts(one, {"logs": [{"message": "gone soon"}]}, "f2")
        self.assertEqual({l["message"] for l in docs_render.merge_facts(both, {"logs": []}, "f1")["logs"]},
                         {"app start", "gone soon"}, "still claimed by f2")
        app_written = docs_render.merge_facts(base, {"logs": [{"message": "app start"}]}, "f1")
        self.assertEqual({l["message"] for l in docs_render.merge_facts(app_written, {"logs": []}, "f1")["logs"]},
                         {"app start"}, "the app agent's entry stays")

    def test_manual_overrides_and_placeholders(self):
        facts_file = self.repo.path / "docs/.docgen/facts/pay.json"
        self.tool("assemble", "--app-state", self.state, code=0)
        op = (self.repo.path / "docs/pay/operator-guide.md").read_text()
        self.assertIn("Isi di `docs/.docgen/facts/pay.json` → `manual.alerts`", op)
        facts = json.loads(facts_file.read_text())
        facts["manual"] = {"escalation": ["@oncall-pay"], "alerts": [{"name": "PayDown", "severity": "page", "when": {"id": "Semua gagal"}}]}
        facts_file.write_text(json.dumps(facts))
        self.tool("render", "--app-state", self.state, code=0)
        op = (self.repo.path / "docs/pay/operator-guide.md").read_text()
        self.assertIn("| Eskalasi | @oncall-pay | diisi manual |", op)
        self.assertIn("| `PayDown` |", op)

    def test_owners_snapshot_is_used_until_refreshed(self):
        self.tool("assemble", "--app-state", self.state, code=0)
        self.tool("render", "--app-state", self.state, "--refresh-owners", code=0)
        self.repo.write("CODEOWNERS", "* @someone-new\n")
        self.repo.commit("owners")
        self.assertTrue(self.tool("render", "--app-state", self.state, "--check", code=0)["ok"], "no drift from time or new owners")
        self.tool("render", "--app-state", self.state, "--refresh-owners", code=0)
        self.assertIn("@someone-new", (self.repo.path / "docs/pay/operator-guide.md").read_text())

    def test_keep_blocks_survive_a_rewrite(self):
        self.tool("assemble", "--app-state", self.state, code=0)
        guide = self.repo.path / "docs/pay/operator-guide.md"
        kept = "<!-- app-docs:keep -->\nDeploy lewat ArgoCD, app `pay-prod`.\n<!-- /app-docs:keep -->"
        guide.write_text(guide.read_text().replace("Selain itu,", kept + "\n\nSelain itu,"))
        snap = str(self.repo.path / "keep.json")
        self.assertEqual(self.tool("keep-snapshot", "--app-state", self.state, "--out", snap, code=0)["blocks"], 1)
        guide.write_text(guide.read_text().replace(kept, ""))          # an agent rewrote the section without it
        self.assertEqual(self.tool("keep-restore", "--app-state", self.state, "--before", snap, code=0)["restored"], ["op:setup"])
        text = guide.read_text()
        self.assertIn(kept, text)
        self.assertLess(text.index(kept), text.index('id="app-flow"'), "restored inside its own section")
        plan = json.loads((self.repo.path / self.tool("humanize-plan", "--app-state", self.state, "--skill", "none")["plan"]).read_text())
        self.assertFalse(any("ArgoCD" in p["text"] for p in plan["paragraphs"]), "the humanizer never sees keep blocks")
        page = next(p for p in self.tool("sync-plan")["pages"] if p["key"] == "pay/op")
        prepared = Path(page["prepared_file"]).read_text()
        self.assertIn("ArgoCD", prepared)
        self.assertNotIn("app-docs:keep", prepared)

    def test_readme_keeps_its_keep_block(self):
        self.tool("assemble", "--app-state", self.state, code=0)
        (self.repo.path / "pay/README.md").write_text("old\n<!-- app-docs:keep -->\nLicence: internal.\n<!-- /app-docs:keep -->\n")
        self.tool("readme", code=0)
        readme = (self.repo.path / "pay/README.md").read_text()
        self.assertIn("Licence: internal.", readme)
        self.assertNotEqual(readme.split("\n")[0], "old")

    def test_story_only_fragment_replaces_only_the_story(self):
        self.tool("assemble", "--app-state", self.state, code=0)
        guide = self.repo.path / "docs/pay/dev-guide.md"
        guide.write_text(guide.read_text().replace('<!-- docgen:render id="errors:create" -->',
                                                   "**A. Receive**\n\n1. Old story.\n\n" + '<!-- docgen:render id="errors:create" -->'))
        op = self.repo.path / "docs/pay/operator-guide.md"
        op.write_text(op.read_text().replace('<!-- docgen:render id="if-failed:create" -->',
                                             "**A. Terima**\n\n1. Lama.\n\n" + '<!-- docgen:render id="if-failed:create" -->'))
        fragment = self.repo.path / "docs/.docgen/.work/fragments/pay/create"
        fragment.mkdir(parents=True)
        (fragment / "story-dev.md").write_text("**A. Receive**\n\n1. New story.\n")
        (fragment / "story-op.md").write_text("**A. Terima**\n\n1. Cerita baru.\n")
        self.assertEqual(self.tool("assemble", "--app-state", self.state, code=0)["assembled"], ["create"])
        text = guide.read_text()
        self.assertIn("1. New story.", text)
        self.assertNotIn("Old story", text)
        self.assertIn("![Create: flowchart]", text, "the rest of the section is untouched")
        self.assertIn("1. Cerita baru.", op.read_text())

    def test_drift_survives_a_squash_merge(self):
        self.tool("assemble", "--app-state", self.state, code=0)
        self.repo.commit("assembled docs")
        self.repo.git("checkout", "-q", "-b", "feature")
        self.repo.write("pay/handler.go", HANDLER + "\n// tweak\n")
        feature_sha = self.repo.commit("feature work")
        app = json.loads(Path(self.state).read_text())
        for sec in app["sections"].values():
            sec.update(sha=feature_sha, files=["pay/handler.go"])
            sec.pop("blobs_at", None)
        Path(self.state).write_text(json.dumps(app))
        self.tool("stamp", "--app-state", self.state, code=0)
        self.repo.git("add", "-A")
        self.repo.git("commit", "-q", "-m", "docs on feature")
        self.repo.git("checkout", "-q", "main")
        self.repo.git("merge", "-q", "--squash", "feature")
        self.repo.git("commit", "-q", "-m", "squashed")
        self.repo.git("branch", "-q", "-D", "feature")
        self.repo.git("reflog", "expire", "--expire=now", "--all")
        self.repo.git("gc", "-q", "--prune=now")
        gone = subprocess.run(["git", "-C", str(self.repo.path), "cat-file", "-t", feature_sha], capture_output=True)
        self.assertNotEqual(gone.returncode, 0, "the squashed commit is really gone, so drift must use the blobs")
        drift = self.tool("drift", code=0)
        self.assertTrue(drift["apps"]["pay"]["up_to_date"], drift["apps"]["pay"])

    def test_conversion_check_catches_a_dropped_cell(self):
        snap = str(self.repo.path / "cells.json")
        guide = self.repo.path / "docs/pay/operator-guide.md"
        guide.write_text(guide.read_text().replace("Selain itu,", "| Key | Wajib |\n|---|---|\n| `RETENTION_DAYS` | ya, disimpan 30 hari |\n\nSelain itu,"))
        self.tool("facts-snapshot", "--app-state", self.state, "--out", snap, "--cells", code=0)
        guide.write_text(guide.read_text().replace("| `RETENTION_DAYS` | ya, disimpan 30 hari |", "| `RETENTION_DAYS` | ya |"))
        out = self.tool("facts-diff", "--app-state", self.state, "--before", snap, "--cells")
        self.assertTrue(any("disimpan" in c.get("missing_words", []) for c in out["changes"]), out)

    def test_humanize_plan_reports_metrik_once_per_guide(self):
        skill = self.repo.path / "fake-skill"
        (skill / "scripts").mkdir(parents=True)
        (skill / "scripts/metrik.py").write_text("print('Sebaran panjang kalimat 0.9 PERIKSA')\nprint('Konektor kaku: 0 OK')\n")
        out = self.tool("humanize-plan", "--app-state", self.state, "--skill", str(skill))
        self.assertEqual(out["guide_notes"], ["operator-guide.md: Sebaran panjang kalimat 0.9 PERIKSA"])


if __name__ == "__main__":
    unittest.main()
