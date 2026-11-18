#!/usr/bin/env python3
"""Lay out an app-docs diagram spec with Graphviz and write a styled, editable .drawio file.

    python3 diagram_layout.py spec.json -o out.drawio [--preview out.svg]

The spec says WHAT is in the diagram (nodes, edges, the happy-path spine, notes, zones, sequence
messages, phases). This script decides WHERE everything goes and how it looks, so agents never
hand-place coordinates. Spec format: references/diagrams.md §13. Needs Graphviz `dot` on PATH for
everything except sequence diagrams. Python 3.8+, stdlib only. Exit codes: 0 ok, 2 bad spec or
missing Graphviz.
"""
import argparse
import html
import json
import math
import shutil
import subprocess
import sys
import textwrap

# ---------------------------------------------------------------- palette (diagrams.md §8)

TEXT = "#1A1A1A"
NODE_STYLE = {
    "start":    ("rounded=1;arcSize=50;", "#2F2F2F", "#2F2F2F", "#FFFFFF"),
    "client":   ("rounded=1;arcSize=50;", "#DAE8FC", "#6C8EBF", TEXT),
    "step":     ("rounded=1;arcSize=12;", "#E1D5E7", "#9673A6", TEXT),
    "subflow":  ("shape=process;backgroundOutline=1;size=0.06;fontStyle=1;", "#E1D5E7", "#9673A6", TEXT),
    "decision": ("rhombus;", "#FFF2CC", "#D6B656", TEXT),
    "db":       ("shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=10;", "#D5E8D4", "#82B366", TEXT),
    "file":     ("shape=folder;tabWidth=46;tabHeight=12;tabPosition=left;spacingTop=10;", "#F0E2C8", "#A0844F", TEXT),
    "object":   ("shape=trapezoid;perimeter=trapezoidPerimeter;flipV=1;size=0.1;fixedSize=0;", "#F2D7E9", "#A65C8C", TEXT),
    "cache":    ("shape=hexagon;perimeter=hexagonPerimeter2;size=0.08;fixedSize=0;", "#E2EFDA", "#548235", TEXT),
    "store":    ("shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=10;dashed=1;", "#EEF3EE", "#7A8C7A", TEXT),
    "queue":    ("shape=parallelogram;perimeter=parallelogramPerimeter;fixedSize=1;size=14;", "#FFE6CC", "#D79B00", TEXT),
    "internal": ("rounded=1;arcSize=12;", "#B0E3E6", "#0E8088", TEXT),
    "external": ("rounded=0;dashed=1;", "#F5F5F5", "#666666", TEXT),
    "ok":       ("rounded=1;arcSize=50;fontStyle=1;", "#A9DFBF", "#1E8449", TEXT),
    "err":      ("rounded=1;arcSize=50;fontStyle=1;", "#F8CECC", "#B85450", TEXT),
    "note":     ("shape=note;size=12;align=left;spacingLeft=6;spacingRight=4;fontSize=11;", "#FFF9DB", "#D6B656", TEXT),
    "state":    ("rounded=1;arcSize=30;", "#E1D5E7", "#9673A6", TEXT),
    "initial":  ("ellipse;", "#2F2F2F", "#2F2F2F", "#FFFFFF"),
    "final":    ("ellipse;shape=doubleEllipse;", "#2F2F2F", "#2F2F2F", "#FFFFFF"),
}
# Sequence participant headers draw the participant as what it is.
HEADER_SHAPE = {
    "client":   "shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;labelPosition=center;align=center;",
    "external": "ellipse;shape=cloud;",
    "db": NODE_STYLE["db"][0], "store": NODE_STYLE["store"][0], "file": NODE_STYLE["file"][0],
    "object": NODE_STYLE["object"][0], "cache": NODE_STYLE["cache"][0], "queue": NODE_STYLE["queue"][0],
}
STORAGE = ("db", "file", "object", "cache", "store", "queue")
LEGEND_NAME = {
    "start": "Start / entry", "client": "Client / caller", "step": "Step in this app",
    "subflow": "Sub-flow reference", "decision": "Decision", "db": "Database (table)", "file": "File storage (disk, NFS)",
    "object": "Object storage (bucket)", "cache": "Cache / in-memory store", "store": "Other storage",
    "queue": "Queue / topic", "internal": "Other internal app", "external": "External system",
    "ok": "Success end", "err": "Error end", "note": "Note", "state": "State",
    "initial": "Initial state", "final": "Final state",
}
EDGE_STYLE = {
    "success": ("strokeColor=#1E8449;strokeWidth=2;endArrow=block;endFill=1;", "Main success path"),
    "normal":  ("strokeColor=#333333;endArrow=block;endFill=1;", "Normal flow"),
    "error":   ("strokeColor=#B85450;endArrow=block;endFill=1;", "Error path"),
    "rejoin":  ("strokeColor=#B85450;endArrow=block;endFill=1;", "Error path, continues (shared channel)"),
    "async":   ("strokeColor=#333333;dashed=1;endArrow=open;endFill=0;", "Async / background"),
    "note":    ("strokeColor=#D6B656;dashed=1;endArrow=none;", None),
    "external": ("strokeColor=#333333;dashed=1;endArrow=block;endFill=1;", "Outside the app (cron, other app, manual)"),
}
HAPPY = "#1E8449"
ERROR = "#B85450"
TINT = {"ok": "#E8F5E9", "error": "#FDECEA", "neutral": "#F5F5F5"}
PHASE_FILLS = ["#DAE8FC", "#E1D5E7", "#FFF2CC", "#D5E8D4", "#FFE6CC", "#B0E3E6"]
FONT = "fontFamily=Helvetica;fontSize=12;fontColor=#1A1A1A;"  # explicit color: an unset label color can't be themed
CHAR_W = 6.6      # px per character at 12px Helvetica, generous
LINE_H = 16
MAX_SHAPE_LINES = 3
WRAP = {"decision": 24, "note": 38, "start": 34, "store": 26, "db": 26, "file": 28, "object": 26, "cache": 26, "external": 26, "default": 30}


class SpecError(Exception):
    pass


# ---------------------------------------------------------------- text and sizes

def wrap_label(text, width):
    lines = []
    for raw in str(text).split("\n"):
        lines.extend(textwrap.wrap(raw, width) or [""])
    return lines


def node_size(kind, lines):
    longest = max((len(l) for l in lines), default=1)
    w = longest * CHAR_W + 28
    h = len(lines) * LINE_H + 20
    if kind == "decision":
        w, h = w * 1.45 + 30, h * 1.7 + 10
    elif kind in ("initial", "final"):
        return 22.0, 22.0
    elif kind in ("store", "db"):
        h += 24
    elif kind == "file":
        h += 14
    elif kind in ("object", "cache"):
        w += 30
    elif kind in ("start", "ok", "err", "client"):
        w += 24
    elif kind == "note":
        w = longest * 6.0 + 30
    return max(w, 70.0 if kind == "note" else 110.0), max(h, 40.0)


def cell_value(lines):
    return "<br>".join(html.escape(l) for l in lines)


def text_width(lines, char_w=CHAR_W):
    return max((len(l) for l in lines), default=1) * char_w


# ---------------------------------------------------------------- graphviz

def run_dot(dot_source):
    if not shutil.which("dot"):
        raise SpecError("Graphviz 'dot' not found on PATH (brew install graphviz / apt install graphviz / winget install graphviz)")
    proc = subprocess.run(["dot", "-Tjson"], input=dot_source, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SpecError("dot failed: " + proc.stderr.strip()[:500])
    return json.loads(proc.stdout)


def q(text):
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_points(pos):
    pts = []
    for token in pos.split():
        if token.startswith(("e,", "s,")):
            continue
        x, y = token.split(",")[:2]
        pts.append((float(x), float(y)))
    return pts


def simplify(points):
    out = []
    for p in points:
        if out and abs(out[-1][0] - p[0]) < 0.5 and abs(out[-1][1] - p[1]) < 0.5:
            continue
        out.append(p)
    changed = True
    while changed and len(out) > 2:
        changed = False
        for i in range(1, len(out) - 1):
            a, b, c = out[i - 1], out[i], out[i + 1]
            if abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < 1.0:
                del out[i]
                changed = True
                break
    return out


def orthogonalize(points, vertical_first=True):
    """Replace any diagonal step with a right-angle detour (vertical-horizontal-vertical in top-down
    diagrams), so a route Graphviz couldn't straighten never shows up as a slanted line."""
    out = [points[0]]
    for b in points[1:]:
        a = out[-1]
        if abs(a[0] - b[0]) > 1 and abs(a[1] - b[1]) > 1:
            if vertical_first:
                mid = (a[1] + b[1]) / 2
                out += [(a[0], mid), (b[0], mid)]
            else:
                mid = (a[0] + b[0]) / 2
                out += [(mid, a[1]), (mid, b[1])]
        out.append(b)
    return simplify(out)


def polyline_mid(points):
    total = sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1))
    half, run = total / 2, 0.0
    for i in range(len(points) - 1):
        seg = math.dist(points[i], points[i + 1])
        if run + seg >= half and seg > 0:
            t = (half - run) / seg
            return (points[i][0] + t * (points[i + 1][0] - points[i][0]),
                    points[i][1] + t * (points[i + 1][1] - points[i][1]))
        run += seg
    return points[0]


class Layout:
    """Everything to draw, in draw.io coordinates (y down, origin top-left)."""

    def __init__(self):
        self.nodes = {}       # id -> dict(kind, lines, x, y, w, h)
        self.edges = []       # graph edges
        self.containers = []  # zone boxes
        self.seq = None       # sequence drawing (dict) when type == sequence
        self.kinds_used = set()
        self.edge_kinds_used = set()
        self.legend_extra = []   # (kind, style, text) rows added by the sequence layout
        self.label_overlaps = 0
        self.long_labels = []

    def bounds(self):
        xs, ys = [], []
        for n in list(self.nodes.values()) + self.containers:
            xs += [n["x"], n["x"] + n["w"]]
            ys += [n["y"], n["y"] + n["h"]]
        for e in self.edges:
            for p in e.get("all_points", []):
                xs.append(p[0])
                ys.append(p[1])
        if self.seq:
            xs += [self.seq["left"], self.seq["right"]]
            ys += [0, self.seq["bottom"]]
        return min(xs), min(ys), max(xs), max(ys)


def _zone_index(spec, node):
    order = [z["id"] for z in spec.get("zones", [])]
    return order.index(node["zone"]) if node.get("zone") in order else len(order)


def _graph_layout(spec, rankdir, splines, zones=False):
    layout = Layout()
    nodes = {n["id"]: n for n in spec["nodes"]}
    lines_by_id, size_by_id = {}, {}
    spacing = "nodesep=1.0, ranksep=1.0" if zones else "nodesep=0.6, ranksep=0.7"  # zone diagrams carry long edge labels
    out = ["digraph G {", "graph [rankdir=%s, splines=%s, %s, newrank=true, compound=true, forcelabels=true];" % (rankdir, splines, spacing),
           "node [shape=box, fixedsize=true, label=\"\", margin=0];", "edge [arrowsize=0.6];"]

    def node_decl(n):
        kind = n.get("kind", "step")
        lines = wrap_label(n.get("label", n["id"]), WRAP.get(kind, WRAP["default"]))
        if kind not in ("note", "initial", "final") and len(lines) > MAX_SHAPE_LINES:
            layout.long_labels.append(n["id"])
        w, h = node_size(kind, lines)
        lines_by_id[n["id"]], size_by_id[n["id"]] = lines, (w, h)
        attrs = "width=%.3f, height=%.3f" % (w / 72, h / 72)
        if kind == "decision":
            attrs += ", shape=diamond"   # lines then end on the diamond's edge, not its bounding box
        if n.get("spine"):
            attrs += ", group=spine"
        elif n.get("_lane"):
            attrs += ", group=lane%d" % n["_lane"]
        return "%s [%s];" % (q(n["id"]), attrs)

    if spec.get("type") == "flowchart":
        for nid, lane in _lanes(spec, nodes, {n["id"] for n in spec["nodes"] if n.get("spine")})[0].items():
            nodes[nid]["_lane"] = lane
    if zones:
        zone_order = [z["id"] for z in spec.get("zones", [])]
        zone_label = {z["id"]: z.get("label", z["id"]) for z in spec.get("zones", [])}
        for zid in zone_order:
            out.append("subgraph %s { label=%s; margin=24; style=rounded;" % (q("cluster_" + zid), q(zone_label[zid])))
            out += [node_decl(n) for n in spec["nodes"] if n.get("zone") == zid]
            out.append("}")
        out += [node_decl(n) for n in spec["nodes"] if n.get("zone") not in zone_order]
        first = [q(n["id"]) for n in spec["nodes"] if zone_order and n.get("zone") == zone_order[0]]
        if first:
            out.append("{ rank=min; %s; }" % "; ".join(first))
    else:
        out += [node_decl(n) for n in spec["nodes"]]

    spine = {n["id"] for n in spec["nodes"] if n.get("spine")}
    edges = list(spec.get("edges", []))
    lanes, lane_starts = _lanes(spec, nodes, spine) if spec.get("type") == "flowchart" else ({}, [])
    for a, b in lane_starts:
        # a branch that goes on (not a plain end) starts its own column to the right, on the decision's row
        out.append("{ rank=same; %s; %s; }" % (q(a), q(b)))
    for n in spec["nodes"]:
        if n.get("kind") == "note" and n.get("note_for") in nodes:
            # a note sits on the same row as what it explains: left of the main column, right of side columns
            target = n["note_for"]
            out.append("{ rank=same; %s; %s; }" % (q(n["id"]), q(target)))
            if lanes.get(target, 0) > 0:
                edges.append({"from": target, "to": n["id"], "kind": "note"})
            else:
                edges.append({"from": n["id"], "to": target, "kind": "note"})
    edge_specs = []
    for i, e in enumerate(edges):
        if e["from"] not in nodes or e["to"] not in nodes:
            raise SpecError("edge %d refers to an unknown node: %s -> %s" % (i, e["from"], e["to"]))
        kind = e.get("kind", "normal")
        edge_specs.append((i, e, kind))
        if kind == "rejoin":
            continue  # routed afterwards through the shared channel
        attrs = []
        if zones and _zone_index(spec, nodes[e["to"]]) < _zone_index(spec, nodes[e["from"]]):
            attrs.append("constraint=false")  # data flowing back to an earlier zone mustn't reorder the zones
        if e["from"] in spine and e["to"] in spine:
            attrs.append("weight=100")
        elif lanes.get(e["from"], 0) > 0 and lanes.get(e["from"]) == lanes.get(e["to"]):
            attrs.append("weight=50")
        flat = kind == "note" or (e["from"], e["to"]) in lane_starts
        if e.get("label"):
            label_lines = wrap_label(e["label"], 26)
            attrs.append(("xlabel=%s" if splines == "ortho" and not flat else "label=%s") % q("\\n".join(label_lines)))
            attrs.append("fontsize=11")
        out.append("%s -> %s [%s];" % (q(e["from"]), q(e["to"]), ", ".join(attrs + ["id=%s" % q("e%d" % i)])))
    out.append("}")
    data = run_dot("\n".join(out))

    bb = [float(v) for v in data["bb"].split(",")]
    height = bb[3]

    def tx(p):
        return (p[0] + 40, height - p[1] + 40)

    for obj in data.get("objects", []):
        name = obj.get("name", "")
        if name.startswith("cluster_"):
            x0, y0, x1, y1 = [float(v) for v in obj["bb"].split(",")]
            (ax, ay), (bx, by) = tx((x0, y1)), tx((x1, y0))
            layout.containers.append({"label": obj.get("label", ""), "x": ax, "y": ay, "w": bx - ax, "h": by - ay})
            continue
        if name not in nodes or "pos" not in obj:
            continue
        cx, cy = tx([float(v) for v in obj["pos"].split(",")])
        w, h = size_by_id[name]
        kind = nodes[name].get("kind", "step")
        layout.nodes[name] = {"kind": kind, "lines": lines_by_id[name], "x": cx - w / 2, "y": cy - h / 2, "w": w, "h": h}
        layout.kinds_used.add(kind)

    by_id = {edge.get("id"): edge for edge in data.get("edges", []) if edge.get("style") != "invis"}
    vertical = rankdir in ("TB", "BT")
    for i, e, kind in edge_specs:
        if kind == "rejoin":
            continue
        edge = by_id.get("e%d" % i)
        src, dst = layout.nodes[e["from"]], layout.nodes[e["to"]]
        if edge is not None and "pos" in edge:
            pts = simplify([tx(p) for p in parse_points(edge["pos"])])
        else:   # Graphviz gave up on this route: draw a plain right-angle one
            if vertical:
                pts = [(src["x"] + src["w"] / 2, src["y"] + src["h"]), (dst["x"] + dst["w"] / 2, dst["y"])]
            else:
                pts = [(src["x"] + src["w"], src["y"] + src["h"] / 2), (dst["x"], dst["y"] + dst["h"] / 2)]
        same_column = (e["from"] in spine and e["to"] in spine) or (nodes[e["from"]].get("_lane") and nodes[e["from"]].get("_lane") == nodes[e["to"]].get("_lane"))
        scx, dcx = src["x"] + src["w"] / 2, dst["x"] + dst["w"] / 2
        if vertical and same_column and abs(scx - dcx) < 3 and dst["y"] > src["y"]:
            # the happy path and each side column run dead straight, centre to centre
            pts = [(scx, src["y"] + src["h"]), (scx, dst["y"])]
        if splines == "ortho":
            pts = orthogonalize(pts, vertical_first=vertical)
        label_at = None
        if edge is not None and ("xlp" in edge or "lp" in edge):
            label_at = tx([float(v) for v in edge["xlp" if "xlp" in edge else "lp"].split(",")])
        _add_edge(layout, e, kind, pts, label_at)
    _route_rejoins(layout, [(e, k) for _, e, k in edge_specs if k == "rejoin"])
    _place_labels(layout)
    return layout


ENDS = {"ok", "err", "note", "db", "file", "object", "cache", "store", "queue", "external", "internal", "client"}


def _lanes(spec, nodes, spine):
    """Columns for a flowchart. The spine is column 0. When a decision's branch goes on to more steps
    (rather than ending), that chain gets its own column, started on the decision's row and running
    down. A plain end (success/error end, storage, external system) just goes to the row below."""
    lanes = {nid: 0 for nid in spine}
    starts, continued, next_lane = [], set(), 1
    flow = [e for e in spec.get("edges", []) if e.get("kind") != "rejoin"]
    changed = True
    while changed:
        changed = False
        for e in flow:
            a, b = e["from"], e["to"]
            if a not in lanes or b in lanes or b in spine or nodes.get(b, {}).get("kind") in ENDS:
                continue
            if nodes[a].get("kind") == "decision" and (a in spine or a in continued):
                lanes[b] = next_lane
                starts.append((a, b))
                next_lane += 1
            else:
                lanes[b] = lanes[a]
            continued.add(a)
            changed = True
    return lanes, starts


def _attach(node, point):
    """Relative connection point (0..1) of `point` on `node`'s bounding box."""
    return (min(1.0, max(0.0, (point[0] - node["x"]) / node["w"])), min(1.0, max(0.0, (point[1] - node["y"]) / node["h"])))


def _add_edge(layout, e, kind, pts, label_at=None):
    src, dst = layout.nodes[e["from"]], layout.nodes[e["to"]]
    entry = {"kind": kind, "src": e["from"], "dst": e["to"], "label": e.get("label", ""), "both": e.get("both", False),
             "points": pts[1:-1], "exit": _attach(src, pts[0]), "entry": _attach(dst, pts[-1]), "all_points": pts}
    if label_at and e.get("label"):
        mid = polyline_mid(pts)
        entry["label_offset"] = (label_at[0] - mid[0], label_at[1] - mid[1])
    layout.edges.append(entry)
    layout.edge_kinds_used.add(kind)


def _route_rejoins(layout, rejoins):
    """Error paths that continue later (e.g. into logging) share one vertical channel right of everything."""
    if not rejoins:
        return
    channel_x = max(n["x"] + n["w"] for n in layout.nodes.values()) + 50

    def same_rank(node):
        cy = node["y"] + node["h"] / 2
        return [n for n in layout.nodes.values() if abs(n["y"] + n["h"] / 2 - cy) < 4]
    for e, kind in rejoins:
        src, dst = layout.nodes[e["from"]], layout.nodes[e["to"]]
        start = (src["x"] + src["w"] / 2, src["y"] + src["h"])
        below = max(n["y"] + n["h"] for n in same_rank(src)) + 16
        above = min(n["y"] for n in same_rank(dst)) - 16
        end = (dst["x"] + dst["w"] * 0.8, dst["y"])
        _add_edge(layout, e, kind, simplify([start, (start[0], below), (channel_x, below), (channel_x, above), (end[0], above), end]))
        layout.edges[-1].pop("label_offset", None)
        layout.edges[-1]["label_near_source"] = True


# ---------------------------------------------------------------- label placement

def _label_box(lines, cx, cy):
    w = max(len(l) for l in lines) * 6.0 + 10
    h = len(lines) * 14 + 4
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def _overlap(a, b, pad=3):
    return a[0] < b[2] + pad and b[0] < a[2] + pad and a[1] < b[3] + pad and b[1] < a[3] + pad


def _segment_hits(box, p, q):
    steps = max(1, int(math.dist(p, q) / 4))
    for i in range(steps + 1):
        x = p[0] + (q[0] - p[0]) * i / steps
        y = p[1] + (q[1] - p[1]) * i / steps
        if box[0] < x < box[2] and box[1] < y < box[3]:
            return True
    return False


def _candidates(points, lines):
    """Label centres along an edge: on horizontal runs on the line or just above/below it, on vertical runs beside it."""
    w = max(len(l) for l in lines) * 6.0 + 10
    h = len(lines) * 14 + 4
    total = sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)) or 1
    out = []
    for k in range(1, 20):
        target, run = total * k / 20, 0.0
        for i in range(len(points) - 1):
            seg = math.dist(points[i], points[i + 1])
            if run + seg >= target and seg > 0:
                t = (target - run) / seg
                x = points[i][0] + t * (points[i + 1][0] - points[i][0])
                y = points[i][1] + t * (points[i + 1][1] - points[i][1])
                if abs(points[i][0] - points[i + 1][0]) < 1:
                    out += [(x + w / 2 + 6, y), (x - w / 2 - 6, y)]
                else:
                    out += [(x, y), (x, y - h / 2 - 5), (x, y + h / 2 + 5)]
                break
            run += seg
    return out


def _place_labels(layout):
    """Slide every edge label along its own edge to the spot that collides least with shapes, other labels
    and other lines. Graphviz places labels one by one and lets them overlap; this pass doesn't."""
    obstacles = [(n["x"], n["y"], n["x"] + n["w"], n["y"] + n["h"]) for n in layout.nodes.values()]
    obstacles += [(c["x"], c["y"], c["x"] + c["w"], c["y"] + 24) for c in layout.containers]
    placed = []
    labelled = [e for e in layout.edges if e["label"] and not e.get("label_near_source") and e["kind"] != "note"]
    labelled.sort(key=lambda e: -len(e["label"]))
    for e in labelled:
        lines = wrap_label(e["label"], 26)
        pts = e["all_points"]
        mid = polyline_mid(pts)
        start = (mid[0] + e["label_offset"][0], mid[1] + e["label_offset"][1]) if e.get("label_offset") else mid
        best, best_cost = None, None
        for rank, c in enumerate([start] + _candidates(pts, lines)):
            box = _label_box(lines, *c)
            cost = 1000 * sum(_overlap(box, o) for o in obstacles) + 1000 * sum(_overlap(box, b) for b in placed)
            cost += 30 * sum(_segment_hits(box, other["all_points"][i], other["all_points"][i + 1])
                             for other in layout.edges if other is not e for i in range(len(other["all_points"]) - 1))
            cost += rank * 0.5
            if best_cost is None or cost < best_cost:
                best, best_cost = c, cost
        box = _label_box(lines, *best)
        if any(_overlap(box, o) for o in obstacles + placed):
            layout.label_overlaps += 1
        placed.append(box)
        e["label_offset"] = (best[0] - mid[0], best[1] - mid[1])


# ---------------------------------------------------------------- sequence

SEQ_TOP = 20.0
HEADER_H = 56.0
BAR_W = 12.0


def _message_color(kind, frm_kind, to_kind):
    """Arrow color tells what the message is: red error, storage color for storage access,
    external color for calls to outside systems, green for the happy path."""
    if kind == "error":
        return ERROR, "Error / early exit"
    other = to_kind if kind in ("sync", "async") else frm_kind
    if other in STORAGE:
        return NODE_STYLE[other][2], LEGEND_NAME[other] + " access"
    if other == "external":
        return NODE_STYLE["external"][2], "External system call"
    return HAPPY, "Happy path"


def _sequence_layout(spec):
    layout = Layout()
    parts = spec["participants"]
    index = {p["id"]: i for i, p in enumerate(parts)}
    pkind = {p["id"]: p.get("kind", "step") for p in parts}
    flat = []

    def walk(steps, depth):
        for step in steps:
            if "phase" in step:
                flat.append(("phase-start", step, depth))
                walk(step.get("steps", []), depth)
                flat.append(("phase-end", step, depth))
            elif "frame" in step:
                flat.append(("frame-start", step, depth))
                walk(step.get("steps", []), depth + 1)
                for alt in step.get("else", []):
                    flat.append(("else", alt, depth))
                    walk(alt.get("steps", []), depth + 1)
                flat.append(("frame-end", step, depth))
            elif "note" in step:
                if step.get("over") not in index:
                    raise SpecError("note refers to an unknown participant: %s" % step.get("over"))
                flat.append(("note", step, depth))
            else:
                if step.get("from") not in index or step.get("to") not in index:
                    raise SpecError("message refers to an unknown participant: %s -> %s" % (step.get("from"), step.get("to")))
                flat.append(("msg", step, depth))
    walk(spec.get("steps", []), 0)
    has_phases = any(k == "phase-start" for k, _, _ in flat)

    # column widths: every label that spans a gap fits in it, self-call labels and notes fit right of their lifeline
    gaps = [190.0] * max(1, len(parts) - 1)
    tail = 40.0

    def need_right(col, width):
        nonlocal tail
        if col < len(parts) - 1:
            gaps[col] = max(gaps[col], width)
        else:
            tail = max(tail, width)
    for kind, step, _ in flat:
        if kind == "note":
            need_right(index[step["over"]], text_width(wrap_label(step["note"], 34), 6.0) + 60)
        elif kind == "msg" and step["from"] == step["to"]:
            need_right(index[step["from"]], text_width(wrap_label(step.get("label", ""), 46)) + 90)
        elif kind == "msg":
            a, b = sorted((index[step["from"]], index[step["to"]]))
            need = text_width(wrap_label(step.get("label", ""), 46)) + 70
            for g in range(a, b):
                gaps[g] = max(gaps[g], need / (b - a))
    head_w = [max(130.0, text_width(wrap_label(p.get("label", p["id"]), 22)) + 30) for p in parts]
    band_label_w = 120.0 if has_phases else 0.0
    xs, x = [], band_label_w + max(head_w[0] / 2, 70.0) + 40
    for i in range(len(parts)):
        xs.append(x)
        if i < len(gaps):
            x += max(gaps[i], (head_w[i] + head_w[min(i + 1, len(parts) - 1)]) / 2 + 30)

    seq = {"phases": [], "sections": [], "frames": [], "messages": [], "notes": [], "bars": [], "lifelines": []}
    y = SEQ_TOP + HEADER_H + 46
    number = 0
    frames, phases = [], []
    open_bars = {p["id"]: [] for p in parts}
    last_y = {p["id"]: None for p in parts}

    def frame_right(right):
        for f in frames:
            f["right"] = max(f["right"], right)

    for kind, step, depth in flat:
        if kind == "phase-start":
            phases.append({"label": step["phase"], "y0": y - 22})
            y += 8
        elif kind == "phase-end":
            phase = phases.pop()
            seq["phases"].append({"label": phase["label"], "y0": phase["y0"], "y1": y - 6})
            y += 26
        elif kind == "frame-start":
            tone = step.get("tone") or ("error" if step["frame"] == "break" else "neutral")
            frames.append({"step": step, "y0": y - 6, "depth": depth, "sections": [{"y0": y - 6, "tone": tone, "label": None}],
                           "cols": set(), "right": 0.0})
            y += 34
        elif kind == "else":
            frame = frames[-1]
            frame["sections"][-1]["y1"] = y
            frame["sections"].append({"y0": y, "tone": step.get("tone", "neutral"), "label": step.get("label", "")})
            y += 30
        elif kind == "frame-end":
            frame = frames.pop()
            frame["sections"][-1]["y1"] = y + 6
            cols = frame["cols"] or {0, len(parts) - 1}
            inset = frame["depth"] * 10
            x0 = xs[min(cols)] - 70 + inset
            x1 = max(xs[max(cols)] + 70 - inset, frame["right"] + 12,
                     x0 + 70 + len(frame["step"].get("label", "")) * CHAR_W)
            seq["frames"].append({"type": frame["step"]["frame"], "label": frame["step"].get("label", ""), "x": x0, "y": frame["y0"],
                                  "w": x1 - x0, "h": y + 6 - frame["y0"], "sections": frame["sections"]})
            for f in frames:
                f["cols"] |= cols
            frame_right(x1 + 10)
            y += 18
        elif kind == "note":
            lines = wrap_label(step["note"], 34)
            col = index[step["over"]]
            w, h = text_width(lines, 6.0) + 26, len(lines) * 14 + 12
            seq["notes"].append({"lines": lines, "x": xs[col] + BAR_W, "y": y - 8, "w": w, "h": h})
            for f in frames:
                f["cols"].add(col)
            frame_right(xs[col] + BAR_W + w)
            y += h + 10
        else:
            number += 1
            msg_kind = step.get("kind", "sync")
            frm, to = step["from"], step["to"]
            lines = wrap_label(step.get("label", ""), 46)
            a, b = xs[index[frm]], xs[index[to]]
            for f in frames:
                f["cols"] |= {index[frm], index[to]}
            label_h = len(lines) * 14
            color, meaning = _message_color(msg_kind, pkind[frm], pkind[to])
            if frm == to:
                pts = [(a + BAR_W / 2, y), (a + 46, y), (a + 46, y + 26), (a + BAR_W / 2 + 6, y + 26)]
                box = (a + 56, y - 2, text_width(lines) + 10, max(label_h, 30))
                frame_right(box[0] + box[2])
                seq["bars"].append({"pid": frm, "y0": y + 14, "y1": y + 34, "depth": len(open_bars[frm]) + 1})
                y_end = y + max(26, label_h)
            else:
                y += label_h
                if msg_kind in ("sync", "async"):
                    open_bars[to].append(y)
                elif open_bars[frm] and not frames:
                    # a reply inside alt/break/opt is only one possible ending: the bar runs on to the real end
                    start = open_bars[frm].pop()
                    seq["bars"].append({"pid": frm, "y0": start, "y1": y, "depth": len(open_bars[frm])})
                pts = [(a, y), (b, y)]
                box = None
                y_end = y
            seq["messages"].append({"kind": msg_kind, "color": color, "lines": lines, "points": pts, "number": number, "label_box": box})
            layout.legend_extra.append(("msg", color, meaning))
            last_y[frm] = last_y[to] = y_end
            y = y_end + 30
    for pid, starts in open_bars.items():
        for depth, start in enumerate(starts):
            seq["bars"].append({"pid": pid, "y0": start, "y1": max(start + 20, (last_y[pid] or start) + 6), "depth": depth})

    bottom = y + 10
    right = max([xs[-1] + tail] + [f["x"] + f["w"] for f in seq["frames"]] + [n["x"] + n["w"] for n in seq["notes"]] +
                [m["label_box"][0] + m["label_box"][2] for m in seq["messages"] if m["label_box"]]) + 20
    for i, p in enumerate(parts):
        kind = pkind[p["id"]]
        layout.kinds_used.add(kind)
        seq["lifelines"].append({"pid": p["id"], "kind": kind, "lines": wrap_label(p.get("label", p["id"]), 22),
                                 "x": xs[i], "w": head_w[i], "top": SEQ_TOP, "bottom": bottom})
    for bar in seq["bars"]:
        bar["x"] = xs[index[bar["pid"]]] - BAR_W / 2 + 6 * bar["depth"]
        bar["kind"] = pkind[bar["pid"]]
    seq.update({"xs": xs, "left": 8.0, "right": right, "bottom": bottom, "numbered": number > 0, "band_label_w": band_label_w})
    layout.seq = seq
    return layout


# ---------------------------------------------------------------- draw.io output

def _style(base, fill, stroke, font):
    return "%swhiteSpace=wrap;html=1;%sfillColor=%s;strokeColor=%s;fontColor=%s;" % (base, FONT, fill, stroke, font)


class Drawio:
    def __init__(self):
        self.cells = []
        self.next_id = 2

    def new_id(self):
        self.next_id += 1
        return "c%d" % self.next_id

    def vertex(self, value, style, x, y, w, h, cell_id=None):
        cell_id = cell_id or self.new_id()
        self.cells.append('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1"><mxGeometry x="%.1f" y="%.1f" width="%.1f" height="%.1f" as="geometry"/></mxCell>'
                          % (cell_id, html.escape(value, quote=True), style, x, y, w, h))
        return cell_id

    def edge(self, value, style, src=None, dst=None, points=(), source_point=None, target_point=None, offset=None, label_x=None):
        geo = ['<mxGeometry relative="1"%s as="geometry">' % (' x="%.2f"' % label_x if label_x is not None else "")]
        if source_point:
            geo.append('<mxPoint x="%.1f" y="%.1f" as="sourcePoint"/>' % source_point)
        if target_point:
            geo.append('<mxPoint x="%.1f" y="%.1f" as="targetPoint"/>' % target_point)
        if points:
            geo.append('<Array as="points">' + "".join('<mxPoint x="%.1f" y="%.1f"/>' % p for p in points) + "</Array>")
        if offset:
            geo.append('<mxPoint x="%.1f" y="%.1f" as="offset"/>' % offset)
        geo.append("</mxGeometry>")
        ends = (' source="%s"' % src if src else "") + (' target="%s"' % dst if dst else "")
        self.cells.append('<mxCell id="%s" value="%s" style="%s" edge="1" parent="1"%s>%s</mxCell>'
                          % (self.new_id(), html.escape(value, quote=True), style, ends, "".join(geo)))

    def xml(self, name):
        return ('<mxfile host="app-docs"><diagram name="%s" id="docgen">'
                '<mxGraphModel grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="0" pageScale="1" background="#FFFFFF" math="0" shadow="0">'
                '<root><mxCell id="0"/><mxCell id="1" parent="0"/>%s</root></mxGraphModel></diagram></mxfile>\n'
                % (html.escape(name, quote=True), "".join(self.cells)))


def _text_cell(d, lines, x, y, w, h, extra=""):
    d.vertex(cell_value(lines), "text;html=1;%sfontSize=11;align=left;verticalAlign=middle;fillColor=none;strokeColor=none;%s" % (FONT, extra), x, y, w, h)


def write_drawio(layout, title):
    d = Drawio()
    for c in layout.containers:
        d.vertex(c["label"], "rounded=1;arcSize=4;whiteSpace=wrap;html=1;%sfillColor=#F5F5F5;strokeColor=#666666;verticalAlign=top;align=left;spacingLeft=10;spacingTop=4;fontStyle=1;dashed=1;"
                 % FONT, c["x"], c["y"], c["w"], c["h"])
    ids = {}
    for nid, n in layout.nodes.items():
        base, fill, stroke, font = NODE_STYLE.get(n["kind"], NODE_STYLE["step"])
        ids[nid] = d.vertex("" if n["kind"] in ("initial", "final") else cell_value(n["lines"]), _style(base, fill, stroke, font),
                            n["x"], n["y"], n["w"], n["h"])
    for e in layout.edges:
        style = "edgeStyle=none;rounded=1;arcSize=16;html=1;%sfontSize=11;labelBackgroundColor=#FFFFFF;%s" % (FONT, EDGE_STYLE[e["kind"]][0])
        style += "exitX=%.3f;exitY=%.3f;exitDx=0;exitDy=0;entryX=%.3f;entryY=%.3f;entryDx=0;entryDy=0;" % (e["exit"] + e["entry"])
        if e.get("both"):
            style += "startArrow=block;startFill=1;"
        d.edge(cell_value(wrap_label(e["label"], 26)) if e["label"] else "", style, ids[e["src"]], ids[e["dst"]],
               e["points"], offset=e.get("label_offset"), label_x=-0.75 if e.get("label_near_source") else None)
    if layout.seq:
        _write_sequence(d, layout.seq)
    _legend(d, layout)
    return d.xml(title)


def _write_sequence(d, seq):
    width = seq["right"] - seq["left"]
    for i, ph in enumerate(seq["phases"]):   # phase bands behind everything, label in the left column
        fill = PHASE_FILLS[i % len(PHASE_FILLS)]
        d.vertex("", "rounded=1;arcSize=3;html=1;fillColor=%s;strokeColor=none;opacity=40;" % fill, seq["left"], ph["y0"], width, ph["y1"] - ph["y0"])
        d.vertex(html.escape(ph["label"]), "text;html=1;%sfontStyle=1;fontSize=13;align=left;verticalAlign=top;whiteSpace=wrap;fillColor=none;strokeColor=none;" % FONT,
                 seq["left"] + 8, ph["y0"] + 6, max(seq["band_label_w"] - 8, 110), 40)
    for fr in seq["frames"]:                  # tinted sections, then the frame outline
        for sec in fr["sections"]:
            d.vertex("", "rounded=0;html=1;fillColor=%s;strokeColor=none;opacity=70;" % TINT.get(sec["tone"], TINT["neutral"]),
                     fr["x"], sec["y0"], fr["w"], sec["y1"] - sec["y0"])
    for ll in seq["lifelines"]:
        x = ll["x"]
        base, fill, stroke, font = NODE_STYLE.get(ll["kind"], NODE_STYLE["step"])
        shape = HEADER_SHAPE.get(ll["kind"], base)
        if ll["kind"] == "client":
            d.vertex(cell_value(ll["lines"]), _style(shape, fill, stroke, font), x - 15, ll["top"], 30, HEADER_H - 18)
        else:
            d.vertex(cell_value(ll["lines"]), _style(shape, fill, stroke, font), x - ll["w"] / 2, ll["top"], ll["w"], HEADER_H)
        d.edge("", "endArrow=none;dashed=1;html=1;strokeColor=#666666;", source_point=(x, ll["top"] + HEADER_H + 4), target_point=(x, ll["bottom"]))
    for bar in seq["bars"]:
        _, fill, stroke, _ = NODE_STYLE.get(bar["kind"], NODE_STYLE["step"])
        d.vertex("", "rounded=0;html=1;fillColor=%s;strokeColor=%s;" % (fill, stroke), bar["x"], bar["y0"], BAR_W, max(bar["y1"] - bar["y0"], 12))
    for fr in seq["frames"]:
        d.vertex(fr["type"], "shape=umlFrame;whiteSpace=wrap;html=1;%sfillColor=none;strokeColor=#666666;width=50;height=22;swimlaneFillColor=none;fontStyle=1;"
                 % FONT, fr["x"], fr["y"], fr["w"], fr["h"])
        if fr["label"]:
            _text_cell(d, [fr["label"]], fr["x"] + 56, fr["y"], max(120, len(fr["label"]) * CHAR_W + 10), 22, "fontSize=12;")
        for sec in fr["sections"][1:]:
            d.edge("", "endArrow=none;dashed=1;html=1;strokeColor=#666666;", source_point=(fr["x"], sec["y0"]), target_point=(fr["x"] + fr["w"], sec["y0"]))
            _text_cell(d, [sec["label"]], fr["x"] + 8, sec["y0"] + 2, max(120, len(sec["label"]) * CHAR_W + 10), 20, "fontSize=12;")
    for m in seq["messages"]:
        pts = m["points"]
        if m["kind"] in ("reply", "error"):
            line = "dashed=1;endArrow=open;endFill=0;"
        elif m["kind"] == "async":
            line = "endArrow=open;endFill=0;"
        else:
            line = "endArrow=block;endFill=1;"
        style = "html=1;rounded=1;%sfontSize=11;verticalAlign=bottom;labelBackgroundColor=none;strokeColor=%s;strokeWidth=1.5;%s" % (FONT, m["color"], line)
        box = m["label_box"]
        d.edge("" if box else cell_value(m["lines"]), style, source_point=pts[0], target_point=pts[-1], points=pts[1:-1])
        if box:
            _text_cell(d, m["lines"], *box)
        # Mermaid-style autonumber: dark circle with a white number where the arrow starts
        d.vertex(str(m["number"]), "ellipse;whiteSpace=wrap;html=1;fontFamily=Helvetica;fontSize=10;fontStyle=1;fillColor=#2F2F2F;strokeColor=#2F2F2F;fontColor=#FFFFFF;",
                 pts[0][0] - 11, pts[0][1] - 11, 22, 22)
    for n in seq["notes"]:
        base, fill, stroke, font = NODE_STYLE["note"]
        d.vertex(cell_value(n["lines"]), _style(base, fill, stroke, font), n["x"], n["y"], n["w"], n["h"])


def _legend(d, layout):
    x0, y0, x1, y1 = layout.bounds()
    rows = [("node", k) for k in NODE_STYLE if k in layout.kinds_used]
    rows += [("edge", k) for k in EDGE_STYLE if k in layout.edge_kinds_used and EDGE_STYLE[k][1]]
    seen = set()
    for kind, color, text in layout.legend_extra:
        if (color, text) not in seen:
            seen.add((color, text))
            rows.append(("msg", (color, text)))
    if layout.seq:
        rows.append(("reply", None))
        if layout.seq["bars"]:
            rows.append(("bar", None))
        if layout.seq["notes"]:
            rows.append(("node", "note"))
        if layout.seq["numbered"]:
            rows.append(("badge", None))
    if not rows:
        return
    width, row_h = 270.0, 24.0
    lx, ly = x1 - width, y1 + 40
    d.vertex("Legend", "rounded=0;whiteSpace=wrap;html=1;%sfillColor=#FFFFFF;strokeColor=#666666;verticalAlign=top;align=left;spacingLeft=8;spacingTop=4;fontStyle=1;"
             % FONT, lx, ly, width, 30 + row_h * len(rows))
    for i, (kind, key) in enumerate(rows):
        ry = ly + 30 + i * row_h
        if kind == "node":
            base, fill, stroke, font = NODE_STYLE[key]
            d.vertex("", _style(base, fill, stroke, font), lx + 10, ry + 3, 30, 16)
            text = LEGEND_NAME[key]
        elif kind == "edge":
            d.edge("", "html=1;rounded=0;" + EDGE_STYLE[key][0], source_point=(lx + 10, ry + 11), target_point=(lx + 40, ry + 11))
            text = EDGE_STYLE[key][1]
        elif kind == "msg":
            d.edge("", "html=1;rounded=0;strokeWidth=1.5;endArrow=block;endFill=1;strokeColor=%s;" % key[0], source_point=(lx + 10, ry + 11), target_point=(lx + 40, ry + 11))
            text = key[1]
        elif kind == "reply":
            d.edge("", "html=1;rounded=0;dashed=1;endArrow=open;endFill=0;strokeColor=#333333;", source_point=(lx + 40, ry + 11), target_point=(lx + 10, ry + 11))
            text = "Reply (dashed, colored like its call)"
        elif kind == "bar":
            d.vertex("", "rounded=0;html=1;fillColor=#E1D5E7;strokeColor=#9673A6;", lx + 20, ry + 2, BAR_W, 20)
            text = "Busy (activation)"
        else:
            d.vertex("1", "ellipse;whiteSpace=wrap;html=1;fontSize=9;fontStyle=1;fillColor=#2F2F2F;strokeColor=#2F2F2F;fontColor=#FFFFFF;", lx + 17, ry + 2, 18, 18)
            text = "Arrow number (used by the story below the diagram)"
        d.vertex(html.escape(text), "text;html=1;%salign=left;verticalAlign=middle;fillColor=none;strokeColor=none;" % FONT,
                 lx + 50, ry, width - 56, row_h)


# ---------------------------------------------------------------- preview (rough SVG, for checking layout only)

def write_preview(layout):
    x0, y0, x1, y1 = layout.bounds()
    w, h = x1 + 300, y1 + 400
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" font-family="Helvetica, Arial, sans-serif" font-size="12"><rect width="100%%" height="100%%" fill="#fff"/>' % (w, h)]
    for c in layout.containers:
        out.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" rx="6" fill="#F5F5F5" stroke="#666" stroke-dasharray="5 3"/><text x="%.0f" y="%.0f" font-weight="bold">%s</text>'
                   % (c["x"], c["y"], c["w"], c["h"], c["x"] + 10, c["y"] + 16, html.escape(c["label"])))
    for e in layout.edges:
        color = "#B85450" if e["kind"] in ("error", "rejoin") else "#1E8449" if e["kind"] == "success" else "#D6B656" if e["kind"] == "note" else "#333"
        dash = ' stroke-dasharray="5 4"' if e["kind"] in ("async", "note", "external") else ""
        pts = e["all_points"]
        out.append('<path d="%s" fill="none" stroke="%s" stroke-width="%s"%s/>' % (_rounded_path(pts), color, 2 if e["kind"] == "success" else 1.2, dash))
        if e["kind"] != "note":
            out.append('<circle cx="%.0f" cy="%.0f" r="3" fill="%s"/>' % (pts[-1][0], pts[-1][1], color))
        if e["label"]:
            if e.get("label_near_source"):
                lx, ly = pts[0][0] + 6, pts[0][1] + 12
            else:
                mx, my = polyline_mid(pts)
                ox, oy = e.get("label_offset", (0, 0))
                lx, ly = mx + ox, my + oy
            out += _text(wrap_label(e["label"], 26), lx, ly, size=11, bg=True)
    for n in layout.nodes.values():
        out += _shape(n["kind"], n["x"], n["y"], n["w"], n["h"], n["lines"])
    if layout.seq:
        out += _preview_sequence(layout.seq)
    out.append("</svg>")
    return "\n".join(out)


def _rounded_path(pts, radius=12.0):
    """SVG path through pts with rounded corners, like draw.io's rounded=1 edges."""
    d = "M%.1f,%.1f" % pts[0]
    for i in range(1, len(pts) - 1):
        p, c, n = pts[i - 1], pts[i], pts[i + 1]
        r = min(radius, math.dist(p, c) / 2, math.dist(c, n) / 2)
        a = (c[0] + (p[0] - c[0]) * r / max(math.dist(p, c), 1e-6), c[1] + (p[1] - c[1]) * r / max(math.dist(p, c), 1e-6))
        b = (c[0] + (n[0] - c[0]) * r / max(math.dist(c, n), 1e-6), c[1] + (n[1] - c[1]) * r / max(math.dist(c, n), 1e-6))
        d += " L%.1f,%.1f Q%.1f,%.1f %.1f,%.1f" % (a[0], a[1], c[0], c[1], b[0], b[1])
    return d + " L%.1f,%.1f" % pts[-1]


def _shape(kind, x, y, w2, h2, lines):
    _, fill, stroke, font = NODE_STYLE.get(kind, NODE_STYLE["step"])
    out = []
    if kind == "decision":
        out.append('<polygon points="%.0f,%.0f %.0f,%.0f %.0f,%.0f %.0f,%.0f" fill="%s" stroke="%s"/>' % (x + w2 / 2, y, x + w2, y + h2 / 2, x + w2 / 2, y + h2, x, y + h2 / 2, fill, stroke))
    elif kind in ("initial", "final"):
        out.append('<circle cx="%.0f" cy="%.0f" r="%.0f" fill="%s"/>' % (x + w2 / 2, y + h2 / 2, w2 / 2, fill))
    elif kind in ("db", "store"):
        dash = ' stroke-dasharray="4 3"' if kind == "store" else ""
        out.append('<path d="M%.0f,%.0f v%.0f a%.0f,8 0 0 0 %.0f,0 v-%.0f a%.0f,8 0 0 0 -%.0f,0 a%.0f,8 0 0 0 %.0f,0" fill="%s" stroke="%s"%s/>'
                   % (x, y + 8, h2 - 16, w2 / 2, w2, h2 - 16, w2 / 2, w2, w2 / 2, w2, fill, stroke, dash))
    elif kind == "file":
        out.append('<path d="M%.0f,%.0f h46 l6,10 h%.0f v%.0f h-%.0f z" fill="%s" stroke="%s"/>' % (x, y, w2 - 52, h2, w2, fill, stroke))
    elif kind == "object":
        out.append('<polygon points="%.0f,%.0f %.0f,%.0f %.0f,%.0f %.0f,%.0f" fill="%s" stroke="%s"/>' % (x, y, x + w2, y, x + w2 * 0.9, y + h2, x + w2 * 0.1, y + h2, fill, stroke))
    elif kind == "cache":
        out.append('<polygon points="%.0f,%.0f %.0f,%.0f %.0f,%.0f %.0f,%.0f %.0f,%.0f %.0f,%.0f" fill="%s" stroke="%s"/>'
                   % (x + w2 * 0.08, y, x + w2 * 0.92, y, x + w2, y + h2 / 2, x + w2 * 0.92, y + h2, x + w2 * 0.08, y + h2, x, y + h2 / 2, fill, stroke))
    else:
        rx = h2 / 2 if kind in ("start", "ok", "err", "client") else 6
        out.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" rx="%.0f" fill="%s" stroke="%s"%s/>' % (x, y, w2, h2, rx, fill, stroke, ' stroke-dasharray="4 3"' if kind == "external" else ""))
    if kind not in ("initial", "final"):
        out += _text(lines, x + w2 / 2, y + h2 / 2, color=font)
    return out


def _preview_sequence(seq):
    out = []
    width = seq["right"] - seq["left"]
    for i, ph in enumerate(seq["phases"]):
        out.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" rx="6" fill="%s" opacity="0.4"/><text x="%.0f" y="%.0f" font-weight="bold" font-size="13">%s</text>'
                   % (seq["left"], ph["y0"], width, ph["y1"] - ph["y0"], PHASE_FILLS[i % len(PHASE_FILLS)], seq["left"] + 10, ph["y0"] + 20, html.escape(ph["label"])))
    for fr in seq["frames"]:
        for sec in fr["sections"]:
            out.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" fill="%s" opacity="0.7"/>' % (fr["x"], sec["y0"], fr["w"], sec["y1"] - sec["y0"], TINT.get(sec["tone"], TINT["neutral"])))
    for ll in seq["lifelines"]:
        x = ll["x"]
        out.append('<line x1="%.0f" y1="%.0f" x2="%.0f" y2="%.0f" stroke="#999" stroke-dasharray="4 4"/>' % (x, ll["top"] + HEADER_H + 4, x, ll["bottom"]))
        if ll["kind"] == "client":
            _, fill, stroke, _ = NODE_STYLE["client"]
            out.append('<circle cx="%.0f" cy="%.0f" r="7" fill="%s" stroke="%s"/><path d="M%.0f,%.0f v14 M%.0f,%.0f h20 M%.0f,%.0f l-8,10 M%.0f,%.0f l8,10" stroke="%s" fill="none"/>'
                       % (x, ll["top"] + 8, fill, stroke, x, ll["top"] + 15, x - 10, ll["top"] + 20, x, ll["top"] + 29, x, ll["top"] + 29, stroke))
            out += _text(ll["lines"], x, ll["top"] + HEADER_H - 6, size=12)
        elif ll["kind"] == "external":
            _, fill, stroke, _ = NODE_STYLE["external"]
            out.append('<ellipse cx="%.0f" cy="%.0f" rx="%.0f" ry="%.0f" fill="%s" stroke="%s" stroke-dasharray="4 3"/>' % (x, ll["top"] + HEADER_H / 2, ll["w"] / 2, HEADER_H / 2, fill, stroke))
            out += _text(ll["lines"], x, ll["top"] + HEADER_H / 2)
        else:
            out += _shape(ll["kind"], x - ll["w"] / 2, ll["top"], ll["w"], HEADER_H, ll["lines"])
    for bar in seq["bars"]:
        _, fill, stroke, _ = NODE_STYLE.get(bar["kind"], NODE_STYLE["step"])
        out.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" fill="%s" stroke="%s"/>' % (bar["x"], bar["y0"], BAR_W, max(bar["y1"] - bar["y0"], 12), fill, stroke))
    for fr in seq["frames"]:
        out.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" fill="none" stroke="#666"/><rect x="%.0f" y="%.0f" width="46" height="20" fill="#fff" stroke="#666"/><text x="%.0f" y="%.0f" font-weight="bold">%s</text><text x="%.0f" y="%.0f">%s</text>'
                   % (fr["x"], fr["y"], fr["w"], fr["h"], fr["x"], fr["y"], fr["x"] + 6, fr["y"] + 15, html.escape(fr["type"]), fr["x"] + 56, fr["y"] + 15, html.escape(fr["label"])))
        for sec in fr["sections"][1:]:
            out.append('<line x1="%.0f" y1="%.0f" x2="%.0f" y2="%.0f" stroke="#666" stroke-dasharray="4 3"/><text x="%.0f" y="%.0f">%s</text>'
                       % (fr["x"], sec["y0"], fr["x"] + fr["w"], sec["y0"], fr["x"] + 8, sec["y0"] + 14, html.escape(sec["label"] or "")))
    for m in seq["messages"]:
        pts = m["points"]
        dash = ' stroke-dasharray="5 4"' if m["kind"] in ("reply", "error") else ""
        out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="1.5"%s/><circle cx="%.0f" cy="%.0f" r="3" fill="%s"/>'
                   % (" ".join("%.0f,%.0f" % p for p in pts), m["color"], dash, pts[-1][0], pts[-1][1], m["color"]))
        if m["label_box"]:
            bx, by, bw, bh = m["label_box"]
            for i, line in enumerate(m["lines"]):
                out.append('<text x="%.0f" y="%.0f" font-size="11">%s</text>' % (bx, by + bh / 2 - 7 * (len(m["lines"]) - 1) + 4 + i * 14, html.escape(line)))
        else:
            out += _text(m["lines"], (pts[0][0] + pts[-1][0]) / 2, pts[0][1] - 8 - 14 * (len(m["lines"]) - 1) / 2 - 2, size=11)
        out.append('<circle cx="%.0f" cy="%.0f" r="11" fill="#2F2F2F"/><text x="%.0f" y="%.0f" fill="#fff" font-size="10" font-weight="bold" text-anchor="middle">%d</text>'
                   % (pts[0][0], pts[0][1], pts[0][0], pts[0][1] + 3.5, m["number"]))
    for n in seq["notes"]:
        out += _shape("note", n["x"], n["y"], n["w"], n["h"], [])
        for i, line in enumerate(n["lines"]):
            out.append('<text x="%.0f" y="%.0f" font-size="11">%s</text>' % (n["x"] + 8, n["y"] + 16 + i * 14, html.escape(line)))
    return out


def _text(lines, cx, cy, size=12, color=TEXT, bg=False):
    out = []
    top = cy - (len(lines) - 1) * (size + 3) / 2 + size / 3
    if bg:
        w = max(len(l) for l in lines) * size * 0.55 + 6
        out.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" fill="#fff"/>' % (cx - w / 2, top - size, w, len(lines) * (size + 3) + 2))
    for i, line in enumerate(lines):
        out.append('<text x="%.0f" y="%.0f" text-anchor="middle" font-size="%d" fill="%s">%s</text>' % (cx, top + i * (size + 3), size, color, html.escape(line)))
    return out


# ---------------------------------------------------------------- main

def build(spec):
    kind = spec.get("type")
    if kind == "flowchart":
        return _graph_layout(spec, spec.get("direction", "TB"), "ortho")
    if kind in ("dataflow", "structure"):
        return _graph_layout(spec, spec.get("direction", "TB"), "ortho", zones=True)
    if kind == "state":
        return _graph_layout(spec, spec.get("direction", "LR"), "polyline")
    if kind == "sequence":
        return _sequence_layout(spec)
    raise SpecError("unknown diagram type %r (flowchart, dataflow, structure, state, sequence)" % kind)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec")
    parser.add_argument("-o", "--output", required=True, help="the .drawio file to write")
    parser.add_argument("--preview", help="also write a rough SVG preview of the layout")
    args = parser.parse_args()
    try:
        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
        layout = build(spec)
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(write_drawio(layout, spec.get("title", "diagram")))
        if args.preview:
            with open(args.preview, "w", encoding="utf-8") as fh:
                fh.write(write_preview(layout))
    except (SpecError, KeyError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    x0, y0, x1, y1 = layout.bounds()
    result = {"ok": True, "nodes": len(layout.nodes), "edges": len(layout.edges), "width": round(x1 + 40), "height": round(y1 + 40),
              "label_overlaps": layout.label_overlaps, "long_labels": layout.long_labels}
    hints = []
    if layout.label_overlaps:
        hints.append("some edge labels still touch a shape or another label: shorten them (full detail goes in the text or table under the diagram)")
    if layout.long_labels:
        hints.append("shapes with more than %d lines: keep the short part in the shape and move the rest into a note" % MAX_SHAPE_LINES)
    if hints:
        result["hints"] = hints
    print(json.dumps(result))


if __name__ == "__main__":
    main()
