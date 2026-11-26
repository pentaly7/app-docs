"""pipeline.py: a whole run with fake agents, resume after an interruption, failures, budgets and workspaces."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_docs_tool import HANDLER, Repo  # noqa: E402
import pipeline  # noqa: E402

PIPELINE = Path(__file__).resolve().parents[1] / "pipeline.py"


def pipe(root, *args):
    proc = subprocess.run([sys.executable, str(PIPELINE), *args, "--root", str(root)], capture_output=True, text=True,
                          env=dict(os.environ, HOME=str(root)))    # no humanizer or draw.io skill from the real home
    try:
        return json.loads(proc.stdout)
    except ValueError:
        raise AssertionError("not JSON (exit %d):\n%s\n%s" % (proc.returncode, proc.stdout, proc.stderr))


def service_repo(name="shop", remote=None):
    repo = Repo(remote or "git@gitlab.example.com:team/%s.git" % name)
    repo.write("go.mod", "module example.com/%s\n\ngo 1.22\n" % name)
    repo.write("cmd/main.go", "package main\n\nfunc main() {}\n")
    repo.write("handler.go", HANDLER)
    repo.commit("code")
    return repo


class FakeAgents:
    """Writes what each real agent would write, just enough for the scripts after it."""

    def __init__(self, humanizer_breaks_facts=False):
        self.humanizer_breaks_facts = humanizer_breaks_facts
        self.calls = []

    def run(self, task):
        repo = Path(self.repo_of(task))
        app = task["description"].split(":", 1)[0]
        kind = task["subagent_type"]
        self.calls.append((kind, task["task"]))
        getattr(self, kind.replace("-", "_"))(repo, app, task["prompt"])

    @staticmethod
    def repo_of(task):
        return next(l.split(": ", 1)[1] for l in task["prompt"].splitlines() if l.startswith("Repo root: "))

    def app_documenter(self, repo, app, prompt):
        if "Mode: app" not in prompt and "Mode: update" not in prompt:
            return
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        sub = "> generated at `%s` on `main`, 2026-11-25, run by Jane Doe" % sha[:7]

        def doc(title, ids):
            out = ["# %s: %s" % (app, title), ""]
            for sid in ids:
                out += ['<!-- docgen:section id="%s" -->' % sid, "## %s" % sid, sub, "", "Teks tentang %s." % sid, ""]
                if sid == "app-flow":
                    out += ['<!-- docgen:flow id="create" -->', ""]
            return "\n".join(out) + "\n"
        dev_ids = ["overview", "app-flow", "glossary"]
        op_ids = ["setup", "app-flow", "owners", "glossary"]
        (repo / "docs" / app).mkdir(parents=True, exist_ok=True)
        (repo / "docs" / app / "dev-guide.md").write_text(doc("Dev Guide", dev_ids))
        (repo / "docs" / app / "operator-guide.md").write_text(doc("User Guide", op_ids))
        sections = {"%s:%s" % (k, s): {"sha": sha, "files": ["handler.go"], "status": "active"} for k, ids in (("dev", dev_ids), ("op", op_ids)) for s in ids}
        state = {"app_id": app, "root": ".", "template_version": 4, "flows": [
            {"id": "create", "label": "POST /pay", "important": True, "group": "core", "entry": "handler.go:3"}],
            "docs": {"dev": "docs/%s/dev-guide.md" % app, "operator": "docs/%s/operator-guide.md" % app}, "sections": sections}
        (repo / "docs/.docgen/apps").mkdir(parents=True, exist_ok=True)
        (repo / ("docs/.docgen/apps/%s.json" % app)).write_text(json.dumps(state))
        (repo / "docs/.docgen/facts").mkdir(parents=True, exist_ok=True)
        if not (repo / ("docs/.docgen/facts/%s.json" % app)).exists():
            (repo / ("docs/.docgen/facts/%s.json" % app)).write_text("{}")

    def flow_documenter(self, repo, app, prompt):
        brief = json.loads((repo / prompt.split("Brief: ", 1)[1].splitlines()[0]).read_text())
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        for f in brief["flows"]:
            frag = repo / f["fragment_dir"]
            frag.mkdir(parents=True, exist_ok=True)
            flow_id = f["flow"]["id"]
            for kind in ("dev", "op"):
                (frag / ("%s.md" % kind)).write_text('<!-- docgen:section id="app-flow/%s" -->\n### %s %s\n\nLangkah 30 detik.\n' % (flow_id, f["numbers"][kind], flow_id))
            (frag / "state.json").write_text(json.dumps({"sections": {"dev:app-flow/%s" % flow_id: {"sha": sha, "files": ["handler.go"]},
                                                                      "op:app-flow/%s" % flow_id: {"sha": sha, "files": ["handler.go"]}}}))

    def goldfish_reviewer(self, repo, app, prompt):
        out = repo / prompt.split("Write findings to: ", 1)[1].splitlines()[0]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"findings": [{"severity": "low", "target": "doc"}]}))

    def doc_fixer(self, repo, app, prompt):
        pass

    def operator_humanizer(self, repo, app, prompt):
        if self.humanizer_breaks_facts and "Facts to restore" not in prompt:
            guide = repo / "docs" / app / "operator-guide.md"
            guide.write_text(guide.read_text().replace("30 detik", "45 detik"))
        elif "Facts to restore" in prompt:
            guide = repo / "docs" / app / "operator-guide.md"
            guide.write_text(guide.read_text().replace("45 detik", "30 detik"))


def drive(root, action, agents, stop_after=None):
    """Play the orchestrator: launch, 'finish' agents, report them done, until done/stop."""
    launched = 0
    while action["action"] in ("agents", "wait", "classify", "ask"):
        if action["action"] == "classify":
            chosen = {r["repo"]: [{"path": c["path"], "id": c["suggested_id"], "kind": "backend"} for c in r["candidates"]] for r in action["repos"]}
            action = pipe(root, "apps", "--json", json.dumps(chosen))
            continue
        if action["action"] == "ask":
            raise AssertionError("unexpected question: %s" % action)
        if action["action"] == "wait":
            raise AssertionError("waiting with nothing to report: %s" % action)
        for task in action["launch"]:
            launched += 1
            if stop_after is not None and launched > stop_after:
                return action
            agents.run(task)
        action = pipe(root, "done", *sum((["--task", t["task"]] for t in action["launch"]), []))
    return action


class WholeRun(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="docgen-pipe-"))
        repo = service_repo()
        self.root = self.tmp / "shop"
        shutil.move(str(repo.path), self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def state(self):
        return json.loads((self.root / "docs/.docgen/state.json").read_text())

    def test_fresh_run_goes_through_every_step(self):
        agents = FakeAgents()
        action = drive(self.root, pipe(self.root, "start", "--unattended"), agents)
        self.assertEqual(action["action"], "done", action)
        self.assertEqual([k for k, _ in agents.calls], ["app-documenter", "flow-documenter", "goldfish-reviewer", "doc-fixer", "operator-humanizer"])
        app = self.state()["apps"]["shop"]
        self.assertEqual(app["stage"], "done")
        self.assertNotIn("job", app)
        guide = (self.root / "docs/shop/operator-guide.md").read_text()
        self.assertIn("app-flow/create", guide, "assembled")
        self.assertIn("shop  ✅ fresh", action["say"])
        self.assertIn("/app-docs:sync", action["say"])
        self.assertIn(".work/", (self.root / "docs/.docgen/.gitignore").read_text())
        # nothing changed since: a second run has nothing to do
        again = pipe(self.root, "start", "--unattended")
        self.assertEqual(again["action"], "done")
        self.assertNotIn("/app-docs:sync", again["say"])

    def test_code_change_runs_an_update_scoped_to_changed_sections(self):
        agents = FakeAgents()
        self.assertEqual(drive(self.root, pipe(self.root, "start", "--unattended"), agents)["action"], "done")
        git = lambda *a: subprocess.run(["git", "-C", str(self.root), *a], check=True, capture_output=True)
        git("add", "-A")
        git("commit", "-q", "-m", "docs")
        (self.root / "handler.go").write_text(HANDLER + "\nfunc Extra() {}\n")
        git("commit", "-q", "-am", "code")
        agents = FakeAgents()
        prompts = []
        original = agents.run
        agents.run = lambda task: (prompts.append(task["prompt"]), original(task))
        action = drive(self.root, pipe(self.root, "start", "--unattended"), agents)
        self.assertEqual(action["action"], "done", action)
        self.assertEqual([k for k, _ in agents.calls][:2], ["app-documenter", "flow-documenter"])
        self.assertIn("Mode: update", prompts[0])
        self.assertIn('"stale_sections"', prompts[0])
        review = next(p for p in prompts if "Review scope:" in p)
        self.assertNotIn("all sections", review)
        self.assertIn("shop  ✅ update", action["say"])

    def test_prompts_carry_the_reading_list_for_their_mode(self):
        action = pipe(self.root, "start", "--unattended")
        if action["action"] == "classify":
            action = pipe(self.root, "apps", "--json", json.dumps({str(self.root): [{"path": ".", "id": "shop", "kind": "backend"}]}))
        prompt = action["launch"][0]["prompt"]
        self.assertIn("Mode: app", prompt)
        self.assertIn("diagrams-style.md", prompt, "Mermaid mode reads the style rules")
        self.assertNotIn("diagrams-spec.md", prompt)
        self.assertNotIn("state-machines.md", prompt, "FSM is off")

    def test_humanizer_gets_one_retry_when_it_changes_a_fact(self):
        agents = FakeAgents(humanizer_breaks_facts=True)
        action = drive(self.root, pipe(self.root, "start", "--unattended"), agents)
        self.assertEqual(action["action"], "done", action)
        self.assertEqual([k for k, _ in agents.calls].count("operator-humanizer"), 2)
        self.assertIn("30 detik", (self.root / "docs/shop/operator-guide.md").read_text())

    def test_interrupted_flow_agent_is_recovered_from_its_fragment(self):
        agents = FakeAgents()
        action = drive(self.root, pipe(self.root, "start", "--unattended"), agents, stop_after=1)
        self.assertEqual(action["launch"][0]["subagent_type"], "flow-documenter")
        agents.run(action["launch"][0])            # it finished, but the session ended before `done`
        resumed = pipe(self.root, "start", "--unattended")
        self.assertEqual(resumed["launch"][0]["subagent_type"], "goldfish-reviewer", "the flow isn't redone")
        self.assertEqual(drive(self.root, resumed, agents)["action"], "done")

    def test_a_failed_agent_fails_its_app_and_the_next_run_retries_the_step(self):
        action = pipe(self.root, "start", "--unattended")
        action = drive(self.root, action, FakeAgents(), stop_after=0)
        task = action["launch"][0]["task"]
        out = pipe(self.root, "done", "--failed", task, "--error", "context limit")
        self.assertEqual(out["action"], "done")
        self.assertIn("failed at app: context limit", out["say"])
        retry = pipe(self.root, "start", "--unattended")
        self.assertEqual(retry["launch"][0]["subagent_type"], "app-documenter")
        self.assertEqual(drive(self.root, retry, FakeAgents())["action"], "done")
        self.assertEqual(self.state()["apps"]["shop"]["stage"], "done")

    def test_a_review_without_findings_file_fails_the_app(self):
        agents = FakeAgents()
        agents.goldfish_reviewer = lambda *a: None
        action = drive(self.root, pipe(self.root, "start", "--unattended"), agents)
        self.assertIn("failed at review", action["say"])

    def test_questions_are_asked_once_for_the_whole_run(self):
        (self.root / "handler.go").write_text(HANDLER + "\n// wip\n")
        action = pipe(self.root, "start")
        if action["action"] == "classify":
            action = pipe(self.root, "apps", "--json", json.dumps({str(self.root): [{"path": ".", "id": "shop", "kind": "backend"}]}))
        self.assertEqual(action["action"], "ask")
        self.assertEqual([q["id"] for q in action["questions"]], ["dirty"])
        self.assertEqual(pipe(self.root, "answer", "dirty=commit-first")["action"], "stop")

    def test_legacy_mid_run_apps_are_refused_until_confirmed(self):
        self.root.joinpath("docs/.docgen").mkdir(parents=True)
        self.root.joinpath("docs/.docgen/state.json").write_text(json.dumps({"template_version": 4, "humanizer_version": pipeline.dt.HUMANIZER_VERSION, "diagram_version": pipeline.dt.DIAGRAM_VERSION,
                                                                                "story_version": pipeline.dt.STORY_VERSION, "apps": {"shop": {"root": ".", "stage": "drafted"}}, "docmost": {}}))
        action = pipe(self.root, "start")
        self.assertEqual(action["action"], "ask")
        self.assertIn("legacy", [q["id"] for q in action["questions"]])
        self.assertEqual(pipe(self.root, "answer", "legacy=stop")["action"], "stop")
        action = pipe(self.root, "answer", "legacy=start-fresh")
        self.assertEqual(action["action"], "agents")
        self.assertEqual(action["launch"][0]["subagent_type"], "app-documenter")


class Workspace(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="docgen-pipe-ws-"))
        self.made = []
        for name, where in (("db-service", "db-service"), ("wallet", "group/wallet"), ("shop", "shop")):
            repo = service_repo(name)
            target = self.root / where
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(repo.path), target)
        (self.root / "shop/.env.example").write_text("WALLET_URL=http://wallet:8080\n")
        (self.root / "group/wallet/.env.example").write_text("DB_SERVICE_URL=http://db-service\n")
        (self.root / "db-service/.env.example").write_text("DB_DSN=postgres://u:p@localhost/wallet\n")   # a database, not a call
        nested = self.root / "shop/third_party/lib"
        nested.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(nested)], check=True)
        vendored = self.root / "vendor/somelib"
        vendored.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(vendored)], check=True)
        deep = self.root / "a/b/too-deep"
        deep.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(deep)], check=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_discovery_two_levels_skips_vendor_and_nested(self):
        kind, repos = pipeline.discover(self.root)
        self.assertEqual(kind, "workspace")
        self.assertEqual(sorted(p.relative_to(self.root).as_posix() for p in repos), ["db-service", "group/wallet", "shop"])
        kind, repos = pipeline.discover(self.root / "shop")
        self.assertEqual((kind, repos), ("repo", [(self.root / "shop").resolve()]), "inside a repo it's a single-repo run")

    def test_callees_first_and_one_run_for_all_repos(self):
        agents = FakeAgents()
        action = pipe(self.root, "start", "--unattended", "--max-apps", "2")
        workspace = json.loads((self.root / ".app-docs-workspace.json").read_text())
        self.assertEqual([r["path"] for r in workspace["repos"]], ["db-service", "group/wallet", "shop"])
        self.assertEqual(workspace["calls"], {"shop": ["wallet"], "wallet": ["db-service"], "db-service": []})
        action = drive(self.root, action, agents)
        self.assertEqual(action["action"], "done", action)
        self.assertIn("Not started (--max-apps): shop", action["say"])
        first_app_prompt = next(t for k, t in agents.calls if k == "app-documenter")
        self.assertTrue(first_app_prompt.startswith("db-service/"), first_app_prompt)
        action = drive(self.root, pipe(self.root, "start", "--unattended"), agents)
        self.assertEqual(action["action"], "done")
        shop_state = json.loads((self.root / "shop/docs/.docgen/state.json").read_text())
        self.assertEqual(shop_state["apps"]["shop"]["stage"], "done")

    def test_other_repos_are_given_as_gitlab_links(self):
        action = pipe(self.root, "start", "--unattended")
        chosen = {r["repo"]: [{"path": c["path"], "id": c["suggested_id"], "kind": "backend"} for c in r["candidates"]] for r in action["repos"]}
        action = pipe(self.root, "apps", "--json", json.dumps(chosen))
        prompt = action["launch"][0]["prompt"]
        self.assertIn("wallet/wallet (another repo): Dev Guide https://gitlab.example.com/team/wallet/-/blob/HEAD/docs/wallet/dev-guide.md", prompt)


if __name__ == "__main__":
    unittest.main()
