"""3.0 sync: User Guide only, the app page is the User Guide, links across a workspace, calibration shared."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_docs_tool import documented_repo, run  # noqa: E402


class Workspace(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="docgen-ws-"))
        shop, _ = documented_repo()
        wallet, _ = documented_repo()
        wallet.git("remote", "set-url", "origin", "git@gitlab.example.com:team/wallet.git")
        self.shop, self.wallet = self.root / "shop", self.root / "group" / "wallet"
        self.wallet.parent.mkdir()
        shutil.move(str(shop.path), self.shop)
        shutil.move(str(wallet.path), self.wallet)
        (self.root / ".app-docs-workspace.json").write_text(json.dumps(
            {"repos": [{"path": "shop"}, {"path": "group/wallet"}], "docmost": {}}))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def tool(self, repo, *args, code=0):
        return run(repo, *args, "--repo", str(repo), code=code)[1]

    def page(self, repo, key="pay"):
        return next(p for p in self.tool(repo, "sync-plan")["pages"] if p["key"] == key)

    def test_only_the_user_guide_is_planned_and_it_is_the_app_page(self):
        plan = self.tool(self.shop, "sync-plan")
        self.assertEqual([(p["key"], p["parent"]) for p in plan["pages"]], [("pay", None)])
        self.assertNotIn("CreatePayment", Path(plan["pages"][0]["prepared_file"]).read_text(), "no Dev Guide text")

    def test_cross_repo_links_wait_for_the_target_then_resolve(self):
        guide = self.shop / "docs/pay/operator-guide.md"
        guide.write_text(guide.read_text() + "\nLihat [Wallet](https://gitlab.example.com/team/wallet/-/blob/main/docs/pay/operator-guide.md#setup)"
                         " dan [Wallet lokal](../../../group/wallet/docs/pay/operator-guide.md).\n"
                         "Kode: [handler](https://gitlab.example.com/team/shop/-/blob/main/pay/handler.go).\n")
        before = self.page(self.shop)
        text = Path(before["prepared_file"]).read_text()
        self.assertEqual(len(before["links_pending"]), 2)
        self.assertIn("Lihat Wallet dan Wallet lokal.", text, "unsynced targets become plain text")
        self.assertIn("[handler](https://gitlab.example.com/team/shop/-/blob/main/pay/handler.go)", text, "other links untouched")
        self.tool(self.wallet, "sync-record", "--key", "pay", "--url", "https://docmost.example.com/p/wallet")
        after = self.page(self.shop)
        self.assertEqual(after["links_pending"], [])
        self.assertIn("[Wallet](https://docmost.example.com/p/wallet)", Path(after["prepared_file"]).read_text())
        self.assertNotEqual(before["content_hash"], after["content_hash"], "the page is re-synced once its links resolve")
        self.assertIn("gitlab.example.com/team/wallet", guide.read_text(), "the markdown keeps its GitLab link")

    def test_calibration_is_shared_and_the_workspace_wins(self):
        self.tool(self.wallet, "sync-record", "--method", "paste-markdown")
        self.tool(self.shop, "sync-record", "--root-url", "https://docmost.example.com/s/ops", "--method", "clipboard-markdown",
                  "--image-method", "file-upload", "--list-numbers", "bold")
        plan = self.tool(self.wallet, "sync-plan")
        self.assertEqual((plan["root_url"], plan["method"], plan["image_method"], plan["list_numbers"]),
                         ("https://docmost.example.com/s/ops", "clipboard-markdown", "file-upload", "bold"))
        workspace = json.loads((self.root / ".app-docs-workspace.json").read_text())
        self.assertEqual(workspace["docmost"]["method"], "clipboard-markdown")


    def test_targets_summarise_each_repo_without_page_text(self):
        pipeline = Path(__file__).resolve().parents[1] / "pipeline.py"
        out = json.loads(subprocess.run([sys.executable, str(pipeline), "targets", "--root", str(self.root)],
                                        capture_output=True, text=True).stdout)
        self.assertEqual(out["kind"], "workspace")
        self.assertEqual({Path(r["repo"]).name for r in out["repos"]}, {"shop", "wallet"})
        self.assertEqual(out["to_sync"], 2)
        self.assertFalse(out["calibrated"])
        order = [Path(r["repo"]).name for r in out["repos"]]
        self.assertEqual([Path(out["next"]).name] + [Path(r).name for r in out["after"]], order, "one repo per conversation, in run order")
        first = Path(out["next"])
        self.tool(first, "sync-record", "--key", "pay", "--url", "https://docmost.example.com/p/1",
                  "--content-hash", self.tool(first, "sync-plan")["pages"][0]["content_hash"])
        out = json.loads(subprocess.run([sys.executable, str(pipeline), "targets", "--root", str(self.root)],
                                        capture_output=True, text=True).stdout)
        self.assertEqual((Path(out["next"]).name, out["after"]), (order[1], []))


class SplitTree(unittest.TestCase):
    def test_split_user_guide_pages_hang_under_the_app_page(self):
        repo, _ = documented_repo()
        try:
            folder = repo.path / "docs/pay/operator"
            folder.mkdir()
            (folder / "00-index.md").write_text("# Pay: User Guide\n\nDaftar isi.\n")
            (folder / "01-setup.md").write_text('# Setup\n\n<!-- docgen:section id="setup" -->\n## Setup\n\nTeks.\n')
            state_file = repo.path / "docs/.docgen/apps/pay.json"
            state = json.loads(state_file.read_text())
            state["docs"]["operator"] = "docs/pay/operator"
            state_file.write_text(json.dumps(state))
            plan = run(repo.path, "sync-plan", "--repo", str(repo.path), code=0)[1]
            self.assertEqual([(p["key"], p["parent"], p["container"]) for p in plan["pages"]],
                             [("pay", None, False), ("pay/op/setup", "pay", False)])
            self.assertIn("Daftar isi.", Path(plan["pages"][0]["prepared_file"]).read_text())
        finally:
            repo.cleanup()


if __name__ == "__main__":
    unittest.main()
