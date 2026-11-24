"""Regression tests for the v2.10.1 run report (v2.10.2)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_docs_tool import HANDLER, TOOL, run, v4_repo


class RunFixes(unittest.TestCase):
    def setUp(self):
        self.repo, self.sha = v4_repo()
        self.state = str(self.repo.path / "docs/.docgen/apps/pay.json")

    def tearDown(self):
        self.repo.cleanup()

    def tool(self, *args, code=None, env=None):
        if env:
            proc = subprocess.run([sys.executable, str(TOOL), *args, "--repo", str(self.repo.path)], capture_output=True, text=True,
                                  env=dict(os.environ, **env))
            return json.loads(proc.stdout)
        return run(self.repo.path, *args, "--repo", str(self.repo.path), code=code)[1]

    def test_dirty_only_when_the_section_files_changed(self):
        self.tool("assemble", "--app-state", self.state, code=0)
        app = json.loads(Path(self.state).read_text())
        app["sections"]["dev:overview"]["files"] = ["pay/handler.go"]
        app["sections"]["dev:setup"] = {"sha": self.sha, "files": ["pay/other.go"], "dirty": True}
        Path(self.state).write_text(json.dumps(app))
        guide = self.repo.path / "docs/pay/dev-guide.md"
        guide.write_text(guide.read_text().replace("> generated at `%s` on" % self.sha[:7],
                                                   "> generated at `%s` + uncommitted changes on" % self.sha[:7], 2))
        self.repo.write("unrelated.txt", "noise")            # dirty tree, but not these sections' files
        self.tool("stamp", "--app-state", self.state, code=0)
        app = json.loads(Path(self.state).read_text())
        self.assertFalse(app["sections"]["dev:setup"]["dirty"])
        self.assertNotIn("uncommitted", guide.read_text(), "subtitles follow the per-section flag")
        self.repo.write("pay/handler.go", HANDLER + "// wip\n")
        self.tool("stamp", "--app-state", self.state, code=0)
        app = json.loads(Path(self.state).read_text())
        self.assertTrue(app["sections"]["dev:overview"]["dirty"])
        self.assertIn("> generated at `%s` + uncommitted changes on" % self.sha[:7], guide.read_text())

    def test_sequence_only_required_for_external_flows(self):
        import docs_tool
        flowchart_only = "![x](diagrams/create.flow.drawio.svg)\n"
        self.assertEqual(docs_tool.flow_section_problems(flowchart_only, "dev", {"id": "create", "external": False}), [])
        self.assertEqual(docs_tool.flow_section_problems(flowchart_only, "dev", {"id": "create", "external": True})[0][0], "diagram-missing")

    def test_check_fragment(self):
        frag = self.repo.path / "docs/.docgen/.work/fragments/pay/create"
        dev = frag / "dev.md"
        dev.write_text(dev.read_text() + "\nSee `pay/handler.go:200-210`.\n")
        out = self.tool("check-fragment", "--app-state", self.state, "--fragment-dir", str(frag))
        rules = {p["rule"] for p in out["problems"]}
        self.assertIn("code-ref-lines", rules)
        self.assertIn("image-missing", rules)
        self.assertIn("diagram-missing", rules, "external by default: needs a sequence diagram")

    def test_stage_and_flow_done(self):
        out = subprocess.run([sys.executable, str(TOOL), "stage", "--repo", str(self.repo.path), "--app", "pay", "--stage", "app-done"],
                             capture_output=True, text=True, check=True).stdout
        self.assertIn("pay -> app-done at 20", out)
        subprocess.run([sys.executable, str(TOOL), "flow-done", "--repo", str(self.repo.path), "--app", "pay", "--flows", "create"], check=True, capture_output=True)
        state = json.loads((self.repo.path / "docs/.docgen/state.json").read_text())
        self.assertEqual(state["apps"]["pay"]["flows_done"], ["create"])
        self.assertTrue(state["apps"]["pay"]["stage_at"].endswith("Z"))

    def test_briefs_group_flows(self):
        app = json.loads(Path(self.state).read_text())
        app["flows"] += [{"id": "refund", "label": "POST /refund", "important": True, "group": "core"},
                         {"id": "report", "label": "GET /report", "important": True, "group": "reports"}]
        app["flows"][0]["group"] = "core"
        Path(self.state).write_text(json.dumps(app))
        out = self.tool("briefs", "--app-state", self.state, code=0)
        self.assertEqual(sorted((b["brief"].split("/")[-1], b["flows"]) for b in out["briefs"]),
                         [("core.json", ["create", "refund"]), ("reports.json", ["report"])])

    def test_usage_spend_from_transcripts(self):
        home = Path(tempfile.mkdtemp())
        project = home / "projects" / "-repo"
        (project / "s1" / "subagents").mkdir(parents=True)
        cwd = str(self.repo.path.resolve())

        def msg(mid, ts, out, read, model="claude-sonnet-5-5", side=False):
            return json.dumps({"type": "assistant", "timestamp": ts, "cwd": cwd, "isSidechain": side,
                               "message": {"id": mid, "model": model, "usage": {"input_tokens": 10, "output_tokens": out,
                                                                                  "cache_creation_input_tokens": 5, "cache_read_input_tokens": read}}})
        (project / "s1.jsonl").write_text("\n".join([msg("m0", "2026-11-23T03:00:00Z", 999, 0),       # before the run
                                                     msg("m1", "2026-11-23T05:00:00Z", 100, 1000),
                                                     msg("m1", "2026-11-23T05:00:01Z", 100, 1000)]))  # streamed twice
        (project / "s1" / "subagents" / "agent-a.jsonl").write_text(msg("m2", "2026-11-23T05:10:00Z", 50, 4000, side=True))
        out = self.tool("usage-spend", "--since", "2026-11-23T04:30:00Z", env={"CLAUDE_CONFIG_DIR": str(home)})
        self.assertEqual(out["totals"], {"input": 20, "output": 150, "cache_write": 10, "cache_read": 5000})
        self.assertEqual(out["transcripts"], 2)
        self.assertTrue(any(a["subagent"] for a in out["agents"]))

    def test_fact_warnings_compare_with_whole_dev_guide(self):
        self.tool("assemble", "--app-state", self.state, code=0)
        op = self.repo.path / "docs/pay/operator-guide.md"
        dev = self.repo.path / "docs/pay/dev-guide.md"
        op.write_text(op.read_text().replace("Selain itu,", "Timeout 30 detik, status 504, key `WALLET_TIMEOUT_MS`. Selain itu,"))
        dev.write_text(dev.read_text().replace("It calls the wallet.", "It calls the wallet with a 30 s timeout (`WALLET_TIMEOUT_MS`)."))
        out = self.tool("validate", "--app-state", self.state)
        mismatches = [w for w in out["warnings"] if w.startswith("fact-mismatch")]
        self.assertEqual(len(mismatches), 1, mismatches)
        self.assertIn("1 fact(s)", mismatches[0])
        self.assertIn("504", mismatches[0])

    def test_diagram_uploaded_once_then_linked(self):
        self.tool("assemble", "--app-state", self.state, code=0)
        svg = self.repo.path / "docs/pay/diagrams/create.flow.drawio.svg"
        svg.parent.mkdir(parents=True, exist_ok=True)
        svg.write_text("<svg/>")
        op = self.repo.path / "docs/pay/operator-guide.md"
        op.write_text(op.read_text().replace("Data diperiksa.", "![Create: flowchart](diagrams/create.flow.drawio.svg)\n\nData diperiksa."))
        plan = self.tool("sync-plan")
        dev = next(p for p in plan["pages"] if p["key"] == "pay/dev")
        self.assertEqual(len(dev["images"]), 1)
        subprocess.run([sys.executable, str(TOOL), "sync-record", "--repo", str(self.repo.path), "--key", "pay/dev",
                        "--url", "https://docmost.example.com/p/dev", "--image-urls", json.dumps(["/files/abc/create.flow.drawio.svg"])],
                       check=True, capture_output=True)
        plan = self.tool("sync-plan")
        op_page = next(p for p in plan["pages"] if p["key"] == "pay/op")
        self.assertEqual(op_page["images"], [], "uploaded once, linked here")
        self.assertEqual(op_page["images_linked"], 1)
        self.assertIn("![create.flow.drawio](/files/abc/create.flow.drawio.svg)", Path(op_page["prepared_file"]).read_text())
        subprocess.run([sys.executable, str(TOOL), "sync-record", "--repo", str(self.repo.path), "--remove-key", "pay/dev"],
                       check=True, capture_output=True)
        op_page = next(p for p in self.tool("sync-plan")["pages"] if p["key"] == "pay/op")
        self.assertEqual(len(op_page["images"]), 1, "its page is gone, so upload again")


if __name__ == "__main__":
    unittest.main()
