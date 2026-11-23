"""Tests for diagram_layout.py: every shipped spec example lays out cleanly, and bad specs fail clearly.

    python3 -m unittest discover -s plugins/app-docs/shared/scripts/tests
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAYOUT = HERE.parent / "diagram_layout.py"
EXAMPLES = HERE.parent.parent / "references" / "spec-examples"


def layout(spec_path, out_dir):
    out = Path(out_dir) / (Path(spec_path).stem + ".drawio")
    proc = subprocess.run([sys.executable, str(LAYOUT), str(spec_path), "-o", str(out), "--preview", str(out.with_suffix(".svg"))],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return proc, out


@unittest.skipUnless(shutil.which("dot"), "Graphviz not installed")
class SpecExamples(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_every_example_is_clean(self):
        specs = sorted(EXAMPLES.glob("*.json"))
        self.assertTrue(specs)
        for spec in specs:
            with self.subTest(spec=spec.name):
                proc, out = layout(spec, self.tmp)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                report = json.loads(proc.stdout)
                self.assertEqual(report["label_overlaps"], 0)
                self.assertEqual(report["long_labels"], [])
                root = ET.parse(out).getroot()
                self.assertEqual(root.tag, "mxfile")
                self.assertEqual(len(root.findall("diagram")), 1, "one page per file")
                cells = root.findall(".//mxCell")
                self.assertTrue(any("Legend" in (c.get("value") or "") or "legend" in (c.get("id") or "") for c in cells),
                                "legend present")

    def test_edges_are_rounded(self):
        proc, out = layout(EXAMPLES / "inquiry.flow.json", self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # legend sample lines have no source shape and stay straight
        edges = [c for c in ET.parse(out).getroot().iter("mxCell") if c.get("edge") == "1" and c.get("source")]
        self.assertTrue(edges)
        self.assertTrue(all("rounded=1" in (c.get("style") or "") for c in edges))


class BadSpecs(unittest.TestCase):
    def test_unknown_node_in_edge_fails_with_code_2(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            spec = tmp / "bad.flow.json"
            spec.write_text(json.dumps({"type": "flowchart", "nodes": [{"id": "a", "label": "A", "kind": "start"}],
                                        "edges": [{"from": "a", "to": "missing"}]}))
            proc, _ = layout(spec, tmp)
            self.assertEqual(proc.returncode, 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
