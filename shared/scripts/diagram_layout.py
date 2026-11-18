#!/usr/bin/env python3
"""Lay out an app-docs diagram spec with Graphviz and write a styled, editable .drawio file.

    python3 diagram_layout.py spec.json -o out.drawio [--preview out.svg]

The spec says WHAT is in the diagram (nodes, edges, which nodes form the happy-path spine,
notes, zones, sequence messages). This script decides WHERE everything goes, so agents never
hand-place coordinates. Spec format: references/diagrams.md §13. Needs Graphviz `dot` on PATH.
Python 3.8+, stdlib only. Exit codes: 0 ok, 2 bad spec or missing Graphviz.
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
LEGEND_NAME = {
    "start": "Start / entry", "client": "Client / caller", "step": "Step in this app",
    "subflow": "Sub-flow reference", "decision": "Decision", "db": "Database (table)", "file": "File storage (disk, NFS)",
    "object": "Object storage (bucket)", "cache": "Cache / in-memory store", "store": "Other storage",
    "queue": "Queue / topic", "internal": "Other internal app", "external": "External system",
    "ok": "Success end", "err": "Error end", "note": "Note (full condition)", "state": "State",
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
    # sequence messages
    "sync":    ("strokeColor=#333333;endArrow=block;endFill=1;", "Synchronous call"),
    "reply":   ("strokeColor=#333333;dashed=1;endArrow=open;endFill=0;", "Reply"),
    "seq-error": ("strokeColor=#B85450;dashed=1;endArrow=open;endFill=0;", "Error reply"),
}
FONT = "fontFamily=Helvetica;fontSize=12;fontColor=#1A1A1A;"  # explicit color: an unset label color can't be themed
CHAR_W = 6.6      # px per character at 12px Helvetica, generous
LINE_H = 16
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
    """Nodes, edges and containers in draw.io coordinates (y down, origin top-left)."""

    def __init__(self):
        self.nodes = {}       # id -> dict(kind, lines, x, y, w, h)
        self.edges = []       # dict(kind, src, dst, label, points, exit, entry, label_at)
        self.containers = []  # dict(label, x, y, w, h)
        self.extras = []      # raw vertices (sequence badges, frames, lifelines)
        self.kinds_used = set()
        self.edge_kinds_used = set()

    def bounds(self):
        xs, ys = [], []
        for n in list(self.nodes.values()) + self.containers + self.extras:
            xs += [n["x"], n["x"] + n["w"]]
            ys += [n["y"], n["y"] + n["h"]]
        for x in self.extras:
            if x.get("label_box"):
                bx, by, bw, bh = x["label_box"]
                xs.append(bx + bw)
        for e in self.edges:
            for p in e.get("all_points", []):
                xs.append(p[0])
                ys.append(p[1])
        return min(xs), min(ys), max(xs), max(ys)


def _graph_layout(spec, rankdir, splines, zones=False):
    layout = Layout()
    nodes = {n["id"]: n for n in spec["nodes"]}
    lines_by_id, size_by_id = {}, {}
    spacing = "nodesep=1.0, ranksep=1.0" if zones else "nodesep=0.55, ranksep=0.65"  # zone diagrams carry long edge labels
    out = ["digraph G {", "graph [rankdir=%s, splines=%s, %s, newrank=true, compound=true, forcelabels=true];" % (rankdir, splines, spacing),
           "node [shape=box, fixedsize=true, label=\"\", margin=0];", "edge [arrowsize=0.6];"]
    def node_decl(n):
        kind = n.get("kind", "step")
        lines = wrap_label(n.get("label", n["id"]), WRAP.get(kind, WRAP["default"]))
        w, h = node_size(kind, lines)
        lines_by_id[n["id"]], size_by_id[n["id"]] = lines, (w, h)
        attrs = "width=%.3f, height=%.3f" % (w / 72, h / 72)
        if n.get("spine"):
            attrs += ", group=spine"
        return "%s [%s];" % (q(n["id"]), attrs)

    if zones:
        zone_order = [z["id"] for z in spec.get("zones", [])]
        zone_label = {z["id"]: z.get("label", z["id"]) for z in spec.get("zones", [])}
        for zid in zone_order:
            out.append("subgraph %s { label=%s; margin=24; style=rounded;" % (q("cluster_" + zid), q(zone_label[zid])))
            out += [node_decl(n) for n in spec["nodes"] if n.get("zone") == zid]
            out.append("}")
        out += [node_decl(n) for n in spec["nodes"] if n.get("zone") not in zone_order]
        # The first zone (the callers) is the top row; the rest follows the direction of the data.
        first = [q(n["id"]) for n in spec["nodes"] if zone_order and n.get("zone") == zone_order[0]]
        if first:
            out.append("{ rank=min; %s; }" % "; ".join(first))
    else:
        out += [node_decl(n) for n in spec["nodes"]]

    # notes sit beside their target, on the left; side exits (terminals reached from a spine decision) on the right
    spine = {n["id"] for n in spec["nodes"] if n.get("spine")}
    edges = list(spec.get("edges", []))
    for n in spec["nodes"]:
        if n.get("kind") == "note" and n.get("note_for") in nodes:
            # flat edge note -> target keeps the note on the left of what it explains
            out.append("{ rank=same; %s; %s; }" % (q(n["id"]), q(n["note_for"])))
            edges.append({"from": n["id"], "to": n["note_for"], "kind": "note"})
    edge_specs = []
    for i, e in enumerate(edges):
        if e["from"] not in nodes or e["to"] not in nodes:
            raise SpecError("edge %d refers to an unknown node: %s -> %s" % (i, e["from"], e["to"]))
        kind = e.get("kind", "normal")
        edge_specs.append((i, e, kind))
        if kind == "rejoin":
            continue  # routed afterwards through the shared channel
        attrs = []
        flat_label = False
        target_kind = nodes[e["to"]].get("kind")
        side_exit = (spec.get("type") == "flowchart" and e["from"] in spine and e["to"] not in spine and kind != "note"
                     and (nodes[e["from"]].get("kind") == "decision" or target_kind in ("external", "store", "queue", "internal")))
        if zones and _zone_index(spec, nodes[e["to"]]) < _zone_index(spec, nodes[e["from"]]):
            attrs.append("constraint=false")  # data flowing back to an earlier zone mustn't reorder the zones
        if e["from"] in spine and e["to"] in spine:
            attrs.append("weight=100")
        elif side_exit:
            # branches leave the spine sideways, so the happy path stays one straight column
            out.append("{ rank=same; %s; %s; }" % (q(e["from"]), q(e["to"])))
            flat_label = bool(e.get("label"))
        if e.get("label"):
            label_lines = wrap_label(e["label"], 26)
            # a sideways (flat) edge only gets room between its two shapes from a real label
            attrs.append(("xlabel=%s" if splines == "ortho" and not flat_label else "label=%s") % q("\\n".join(label_lines)))
            attrs.append("fontsize=11")
        out.append("%s -> %s [%s];" % (q(e["from"]), q(e["to"]), ", ".join(attrs) + (", " if attrs else "") + "id=%s" % q("e%d" % i)))
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

    gv_names = {obj["_gvid"]: obj.get("name") for obj in data.get("objects", []) if "_gvid" in obj}
    by_id = {}
    for edge in data.get("edges", []):
        if edge.get("style") == "invis" or "pos" not in edge:
            continue
        by_id[edge.get("id")] = edge
    for i, e, kind in edge_specs:
        if kind == "rejoin":
            continue
        edge = by_id.get("e%d" % i)
        if edge is None:
            continue
        pts = simplify([tx(p) for p in parse_points(edge["pos"])])
        label_at = tx([float(v) for v in edge[("xlp" if "xlp" in edge else "lp")].split(",")]) if ("xlp" in edge or "lp" in edge) else None
        _add_edge(layout, e, kind, pts, label_at)
    _route_rejoins(layout, [(e, k) for _, e, k in edge_specs if k == "rejoin"])
    _place_labels(layout)
    return layout


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
    """Label centres along an edge: on horizontal runs the label sits on the line, on vertical runs beside it."""
    w = max(len(l) for l in lines) * 6.0 + 10
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
                h = len(lines) * 14 + 4
                if abs(points[i][0] - points[i + 1][0]) < 1:   # vertical run
                    out += [(x + w / 2 + 6, y), (x - w / 2 - 6, y)]
                else:                                          # on the line, or just above / below it
                    out += [(x, y), (x, y - h / 2 - 5), (x, y + h / 2 + 5)]
                break
            run += seg
    return out


def _place_labels(layout):
    """Slide every edge label along its own edge to the spot that collides least with shapes, other labels
    and other lines. Graphviz places labels one by one and lets them overlap; this pass doesn't."""
    obstacles = [(n["x"], n["y"], n["x"] + n["w"], n["y"] + n["h"]) for n in layout.nodes.values()]
    obstacles += [(c["x"], c["y"], c["x"] + c["w"], c["y"] + 24) for c in layout.containers]  # container titles
    placed = []
    labelled = [e for e in layout.edges if e["label"] and not e.get("label_near_source") and e["kind"] != "note"]
    labelled.sort(key=lambda e: -len(e["label"]))
    layout.label_overlaps = 0
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
            cost += rank * 0.5   # prefer Graphviz's own spot, then the middle of the edge
            if best_cost is None or cost < best_cost:
                best, best_cost = c, cost
        box = _label_box(lines, *best)
        if any(_overlap(box, o) for o in obstacles + placed):
            layout.label_overlaps += 1
        placed.append(box)
        e["label_offset"] = (best[0] - mid[0], best[1] - mid[1])


def _zone_index(spec, node):
    order = [z["id"] for z in spec.get("zones", [])]
    return order.index(node["zone"]) if node.get("zone") in order else len(order)


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
    def rank_bottom(node):
        cy = node["y"] + node["h"] / 2
        return max(n["y"] + n["h"] for n in layout.nodes.values() if abs(n["y"] + n["h"] / 2 - cy) < 4)
    def rank_top(node):
        cy = node["y"] + node["h"] / 2
        return min(n["y"] for n in layout.nodes.values() if abs(n["y"] + n["h"] / 2 - cy) < 4)
    for e, kind in rejoins:
        src, dst = layout.nodes[e["from"]], layout.nodes[e["to"]]
        start = (src["x"] + src["w"] / 2, src["y"] + src["h"])
        below = rank_bottom(src) + 16
        above = rank_top(dst) - 16
        end = (dst["x"] + dst["w"] * 0.8, dst["y"])
        pts = [start, (start[0], below), (channel_x, below), (channel_x, above), (end[0], above), end]
        _add_edge(layout, e, kind, simplify(pts))
        layout.edges[-1].pop("label_offset", None)
        layout.edges[-1]["label_near_source"] = True


# ---------------------------------------------------------------- sequence

def _sequence_layout(spec):
    layout = Layout()
    parts = spec["participants"]
    index = {p["id"]: i for i, p in enumerate(parts)}
    flat = []

    def walk(steps, depth):
        for step in steps:
            if "frame" in step:
                flat.append(("frame-start", step, depth))
                walk(step.get("steps", []), depth + 1)
                for alt in step.get("else", []):
                    flat.append(("else", alt, depth))
                    walk(alt.get("steps", []), depth + 1)
                flat.append(("frame-end", step, depth))
            else:
                if step["from"] not in index or step["to"] not in index:
                    raise SpecError("message refers to an unknown participant: %s -> %s" % (step["from"], step["to"]))
                flat.append(("msg", step, depth))
    walk(spec.get("steps", []), 0)

    # column gaps wide enough for every label that spans them
    gaps = [190.0] * max(1, len(parts) - 1)
    tail = 0.0   # room right of the last column for its self-message labels
    for kind, step, _ in flat:
        if kind == "msg" and step["from"] == step["to"]:
            col = index[step["from"]]
            need = max(len(l) for l in wrap_label(step.get("label", ""), 46)) * CHAR_W + 90
            if col < len(gaps) and len(parts) > 1:
                gaps[col] = max(gaps[col], need)
            if col == len(parts) - 1:
                tail = max(tail, need)
            continue
        if kind != "msg":
            continue
        a, b = sorted((index[step["from"]], index[step["to"]]))
        lines = wrap_label(step.get("label", ""), 46)
        need = max(len(l) for l in lines) * CHAR_W + 70
        for g in range(a, b):
            gaps[g] = max(gaps[g], need / (b - a))
    head_w = [max(140.0, max(len(l) for l in wrap_label(p.get("label", p["id"]), 22)) * CHAR_W + 30) for p in parts]
    xs, x = [], max(head_w[0] / 2, 70.0) + 40
    for i, p in enumerate(parts):
        xs.append(x)
        if i < len(gaps):
            x += max(gaps[i], (head_w[i] + head_w[min(i + 1, len(parts) - 1)]) / 2 + 30)
    header_h = 48.0
    y = header_h + 50
    number = 0
    frames = []
    for kind, step, depth in flat:
        if kind == "frame-start":
            frames.append({"step": step, "y0": y - 6, "depth": depth, "elses": [], "cols": set(), "right": 0.0})
            y += 34
        elif kind == "else":
            frames[-1]["elses"].append((y + 4, step.get("label", "")))
            y += 30
        elif kind == "frame-end":
            frame = frames.pop()
            cols = frame["cols"] or {0, len(parts) - 1}
            inset = frame["depth"] * 10
            x0 = xs[min(cols)] - 70 + inset
            x1 = max(xs[max(cols)] + 70 - inset, frame["right"] + 12,
                     x0 + 70 + len(frame["step"].get("label", "")) * CHAR_W)   # condition text fits inside
            for f in frames:
                f["cols"] |= cols
                f["right"] = max(f["right"], x1 + 10)
            layout.extras.append({"type": "frame", "label": frame["step"]["frame"], "cond": frame["step"].get("label", ""),
                                  "x": x0, "y": frame["y0"], "w": x1 - x0, "h": y - frame["y0"] + 6, "elses": frame["elses"]})
            y += 18
        else:
            number += 1
            lines = wrap_label(step.get("label", ""), 46)
            a, b = xs[index[step["from"]]], xs[index[step["to"]]]
            for f in frames:
                f["cols"] |= {index[step["from"]], index[step["to"]]}
            label_h = len(lines) * 14
            y += label_h
            msg_kind = step.get("kind", "sync")
            if msg_kind == "error":
                msg_kind = "seq-error"
            if a == b:
                y -= label_h                      # self-message: the label sits right of the loop, not above it
                pts = [(a, y), (a + 46, y), (a + 46, y + 26), (a, y + 26)]
                label_box = (a + 56, y - 2, max(len(l) for l in lines) * CHAR_W + 10, max(label_h, 30))
                for f in frames:
                    f["right"] = max(f["right"], label_box[0] + label_box[2])
                y += max(26, label_h)
            else:
                pts = [(a, y), (b, y)]
                label_box = None
            layout.extras.append({"type": "message", "kind": msg_kind, "lines": lines, "points": pts, "number": number,
                                  "x": min(a, b), "y": y - label_h, "w": abs(b - a) or 46, "h": label_h, "label_box": label_box})
            layout.edge_kinds_used.add(msg_kind)
            y += 30
    bottom = y + 20
    layout.tail = tail
    for i, p in enumerate(parts):
        kind = p.get("kind", "step")
        layout.kinds_used.add(kind)
        layout.extras.append({"type": "lifeline", "kind": kind, "lines": wrap_label(p.get("label", p["id"]), 22),
                              "x": xs[i] - head_w[i] / 2, "y": 30.0, "w": head_w[i], "h": bottom - 30, "header": header_h})
    layout.numbered = number > 0
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


def write_drawio(layout, title):
    d = Drawio()
    for c in layout.containers:
        d.vertex(c["label"], "rounded=1;arcSize=4;whiteSpace=wrap;html=1;%sfillColor=#F5F5F5;strokeColor=#666666;fontColor=%s;verticalAlign=top;align=left;spacingLeft=10;spacingTop=4;fontStyle=1;dashed=1;"
                 % (FONT, TEXT), c["x"], c["y"], c["w"], c["h"])
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
        label_x = -0.75 if e.get("label_near_source") else None
        d.edge(cell_value(wrap_label(e["label"], 26)) if e["label"] else "", style, ids[e["src"]], ids[e["dst"]],
               e["points"], offset=e.get("label_offset"), label_x=label_x)
    for x in layout.extras:
        if x["type"] == "lifeline":
            base, fill, stroke, font = NODE_STYLE.get(x["kind"], NODE_STYLE["step"])
            d.vertex(cell_value(x["lines"]), "shape=umlLifeline;perimeter=lifelinePerimeter;container=0;collapsible=0;recursiveResize=0;outlineConnect=0;size=%d;whiteSpace=wrap;html=1;%sfillColor=%s;strokeColor=%s;fontColor=%s;"
                     % (x["header"], FONT, fill, stroke, font), x["x"], x["y"], x["w"], x["h"])
    for x in layout.extras:
        if x["type"] == "frame":
            d.vertex(x["label"], "shape=umlFrame;whiteSpace=wrap;html=1;%sfillColor=#F5F5F5;strokeColor=#666666;fontColor=%s;width=50;height=22;swimlaneFillColor=none;fontStyle=1;"
                     % (FONT, TEXT), x["x"], x["y"], x["w"], x["h"])
            if x["cond"]:
                d.vertex(html.escape(x["cond"]), "text;html=1;%sfontColor=%s;align=left;verticalAlign=middle;fillColor=none;strokeColor=none;" % (FONT, TEXT),
                         x["x"] + 56, x["y"], max(120, len(x["cond"]) * CHAR_W + 10), 22)
            for ey, label in x["elses"]:
                d.edge("", "endArrow=none;dashed=1;html=1;strokeColor=#666666;", source_point=(x["x"], ey), target_point=(x["x"] + x["w"], ey))
                d.vertex(html.escape(label), "text;html=1;%sfontColor=%s;align=left;fillColor=none;strokeColor=none;" % (FONT, TEXT),
                         x["x"] + 8, ey + 2, max(120, len(label) * CHAR_W + 10), 20)
    for x in layout.extras:
        if x["type"] != "message":
            continue
        pts = x["points"]
        style = "html=1;rounded=1;%sfontSize=11;verticalAlign=bottom;labelBackgroundColor=none;%s" % (FONT, EDGE_STYLE[x["kind"]][0])
        box = x.get("label_box")
        d.edge("" if box else cell_value(x["lines"]), style, source_point=pts[0], target_point=pts[-1], points=pts[1:-1])
        if box:
            d.vertex(cell_value(x["lines"]), "text;html=1;%sfontSize=11;align=left;verticalAlign=middle;fillColor=none;strokeColor=none;" % FONT, *box)
        # Mermaid-style autonumber: dark circle with a white number where the arrow starts
        d.vertex(str(x["number"]), "ellipse;whiteSpace=wrap;html=1;fontFamily=Helvetica;fontSize=10;fontStyle=1;fillColor=#2F2F2F;strokeColor=#2F2F2F;fontColor=#FFFFFF;",
                 pts[0][0] - 11, pts[0][1] - 11, 22, 22)
    _legend(d, layout)
    return d.xml(title)


def _legend(d, layout):
    x0, y0, x1, y1 = layout.bounds()
    rows = [("node", k) for k in NODE_STYLE if k in layout.kinds_used]
    rows += [("edge", k) for k in EDGE_STYLE if k in layout.edge_kinds_used and EDGE_STYLE[k][1]]
    if getattr(layout, "numbered", False):
        rows.append(("badge", None))
    if not rows:
        return
    width, row_h = 250.0, 24.0
    lx, ly = x1 - width, y1 + 40
    d.vertex("Legend", "rounded=0;whiteSpace=wrap;html=1;%sfillColor=#FFFFFF;strokeColor=#666666;fontColor=%s;verticalAlign=top;align=left;spacingLeft=8;spacingTop=4;fontStyle=1;"
             % (FONT, TEXT), lx, ly, width, 30 + row_h * len(rows))
    for i, (kind, key) in enumerate(rows):
        ry = ly + 30 + i * row_h
        if kind == "node":
            base, fill, stroke, font = NODE_STYLE[key]
            d.vertex("", _style(base, fill, stroke, font), lx + 10, ry + 3, 30, 16)
            text = LEGEND_NAME[key]
        elif kind == "edge":
            d.edge("", "html=1;rounded=0;" + EDGE_STYLE[key][0], source_point=(lx + 10, ry + 11), target_point=(lx + 40, ry + 11))
            text = EDGE_STYLE[key][1]
        else:
            d.vertex("1", "ellipse;whiteSpace=wrap;html=1;fontSize=9;fontStyle=1;fillColor=#2F2F2F;strokeColor=#2F2F2F;fontColor=#FFFFFF;", lx + 17, ry + 2, 18, 18)
            text = "Step number (matches the text)"
        d.vertex(html.escape(text), "text;html=1;%sfontColor=%s;align=left;verticalAlign=middle;fillColor=none;strokeColor=none;" % (FONT, TEXT),
                 lx + 50, ry, width - 56, row_h)


# ---------------------------------------------------------------- preview (rough SVG, for checking layout only)

def write_preview(layout):
    x0, y0, x1, y1 = layout.bounds()
    w, h = x1 + 300, y1 + 400
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" font-family="Helvetica" font-size="12"><rect width="100%%" height="100%%" fill="#fff"/>' % (w, h)]
    for c in layout.containers:
        out.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" rx="6" fill="#F5F5F5" stroke="#666" stroke-dasharray="5 3"/><text x="%.0f" y="%.0f" font-weight="bold">%s</text>'
                   % (c["x"], c["y"], c["w"], c["h"], c["x"] + 10, c["y"] + 16, html.escape(c["label"])))
    for x in layout.extras:
        if x["type"] == "lifeline":
            _, fill, stroke, _ = NODE_STYLE.get(x["kind"], NODE_STYLE["step"])
            cx = x["x"] + x["w"] / 2
            out.append('<line x1="%.0f" y1="%.0f" x2="%.0f" y2="%.0f" stroke="#999" stroke-dasharray="4 4"/>' % (cx, x["y"] + x["header"], cx, x["y"] + x["h"]))
            out.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" fill="%s" stroke="%s"/>' % (x["x"], x["y"], x["w"], x["header"], fill, stroke))
            out += _text(x["lines"], cx, x["y"] + x["header"] / 2)
        elif x["type"] == "frame":
            out.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" fill="none" stroke="#666"/><text x="%.0f" y="%.0f" font-weight="bold">%s %s</text>'
                       % (x["x"], x["y"], x["w"], x["h"], x["x"] + 6, x["y"] + 15, html.escape(x["label"]), html.escape(x["cond"])))
            for ey, label in x["elses"]:
                out.append('<line x1="%.0f" y1="%.0f" x2="%.0f" y2="%.0f" stroke="#666" stroke-dasharray="4 3"/><text x="%.0f" y="%.0f">%s</text>'
                           % (x["x"], ey, x["x"] + x["w"], ey, x["x"] + 8, ey + 14, html.escape(label)))
    for e in layout.edges:
        color = "#B85450" if e["kind"] in ("error", "rejoin") else "#1E8449" if e["kind"] == "success" else "#D6B656" if e["kind"] == "note" else "#333"
        dash = ' stroke-dasharray="5 4"' if e["kind"] in ("async", "note", "external") else ""
        pts = e["all_points"]
        out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%s"%s/>' % (" ".join("%.0f,%.0f" % p for p in pts), color, 2 if e["kind"] == "success" else 1.2, dash))
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
        _, fill, stroke, font = NODE_STYLE.get(n["kind"], NODE_STYLE["step"])
        x, y, w2, h2 = n["x"], n["y"], n["w"], n["h"]
        if n["kind"] == "decision":
            out.append('<polygon points="%.0f,%.0f %.0f,%.0f %.0f,%.0f %.0f,%.0f" fill="%s" stroke="%s"/>' % (x + w2 / 2, y, x + w2, y + h2 / 2, x + w2 / 2, y + h2, x, y + h2 / 2, fill, stroke))
        elif n["kind"] in ("initial", "final"):
            out.append('<circle cx="%.0f" cy="%.0f" r="%.0f" fill="%s"/>' % (x + w2 / 2, y + h2 / 2, w2 / 2, fill))
        elif n["kind"] in ("db", "store"):
            dash = ' stroke-dasharray="4 3"' if n["kind"] == "store" else ""
            out.append('<path d="M%.0f,%.0f v%.0f a%.0f,8 0 0 0 %.0f,0 v-%.0f a%.0f,8 0 0 0 -%.0f,0 a%.0f,8 0 0 0 %.0f,0" fill="%s" stroke="%s"%s/>'
                       % (x, y + 8, h2 - 16, w2 / 2, w2, h2 - 16, w2 / 2, w2, w2 / 2, w2, fill, stroke, dash))
        elif n["kind"] == "file":
            out.append('<path d="M%.0f,%.0f h46 l6,10 h%.0f v%.0f h-%.0f z" fill="%s" stroke="%s"/>' % (x, y, w2 - 52, h2, w2, fill, stroke))
        elif n["kind"] == "object":
            out.append('<polygon points="%.0f,%.0f %.0f,%.0f %.0f,%.0f %.0f,%.0f" fill="%s" stroke="%s"/>' % (x, y, x + w2, y, x + w2 * 0.9, y + h2, x + w2 * 0.1, y + h2, fill, stroke))
        elif n["kind"] == "cache":
            out.append('<polygon points="%.0f,%.0f %.0f,%.0f %.0f,%.0f %.0f,%.0f %.0f,%.0f %.0f,%.0f" fill="%s" stroke="%s"/>'
                       % (x + w2 * 0.08, y, x + w2 * 0.92, y, x + w2, y + h2 / 2, x + w2 * 0.92, y + h2, x + w2 * 0.08, y + h2, x, y + h2 / 2, fill, stroke))
        else:
            rx = h2 / 2 if n["kind"] in ("start", "ok", "err", "client") else 6
            out.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" rx="%.0f" fill="%s" stroke="%s"%s/>' % (x, y, w2, h2, rx, fill, stroke, ' stroke-dasharray="4 3"' if n["kind"] == "external" else ""))
        if n["kind"] not in ("initial", "final"):
            out += _text(n["lines"], x + w2 / 2, y + h2 / 2, color=font)
    for x in layout.extras:
        if x["type"] == "message":
            pts = x["points"]
            color = "#B85450" if x["kind"] == "seq-error" else "#333"
            dash = ' stroke-dasharray="5 4"' if x["kind"] in ("reply", "seq-error") else ""
            out.append('<polyline points="%s" fill="none" stroke="%s"%s/><circle cx="%.0f" cy="%.0f" r="3" fill="%s"/>' % (" ".join("%.0f,%.0f" % p for p in pts), color, dash, pts[-1][0], pts[-1][1], color))
            if x.get("label_box"):
                bx, by, bw, bh = x["label_box"]
                for i, line in enumerate(x["lines"]):
                    out.append('<text x="%.0f" y="%.0f" font-size="11">%s</text>' % (bx, by + bh / 2 - 7 * (len(x["lines"]) - 1) + 4 + i * 14, html.escape(line)))
            else:
                mid = (pts[0][0] + pts[-1][0]) / 2
                out += _text(x["lines"], mid, pts[0][1] - 8 - 14 * (len(x["lines"]) - 1) / 2 - 2, size=11)
            out.append('<circle cx="%.0f" cy="%.0f" r="11" fill="#333"/><text x="%.0f" y="%.0f" fill="#fff" font-size="10" font-weight="bold" text-anchor="middle">%d</text>' % (pts[0][0], pts[0][1], pts[0][0], pts[0][1] + 3.5, x["number"]))
    out.append("</svg>")
    return "\n".join(out)


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
              "label_overlaps": getattr(layout, "label_overlaps", 0)}
    if result["label_overlaps"]:
        result["hint"] = "some edge labels still touch a shape or another label: shorten them (full detail goes in the table under the diagram)"
    print(json.dumps(result))


if __name__ == "__main__":
    main()
