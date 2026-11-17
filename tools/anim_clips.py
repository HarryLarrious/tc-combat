#!/usr/bin/env python3
"""Animation clips for the player rig.

    python3 tools/anim_clips.py          writes tc/anim_data.tc
    python3 tools/anim_editor/serve.py   the editor (saves clips, runs this)
    python3 tools/anim_preview.py ...    renders clips to contact sheets

Every clip is a JSON file in anim/clips/<name>.json, the one source of every
animation; edit them with the editor (or by hand). A clip:

  name      its name (the file name too); the game plays clips by name
  kind      "cycle" loops over distance walked (length = blocks per cycle),
            "loop" loops over time (length = ticks), "once" plays once over
            time (length = ticks) and holds its last pose
  interp    "spline": Catmull-Rom through the keys (smooth arcs, for loops
            and cycles); "ease": each key sets how the motion arrives at it
            (its "ease": "smooth" eases in and out, "in" accelerates into
            it (a strike), "out" decelerates into it (a wind-up or settle),
            "linear")
  planted   the root is raised or lowered so the lowest foot touches the
            ground, then the key's "lift" (px) is added: feet never sink or
            float
  counter   the legs turn back against the torso's angles, so leaning or
            twisting the torso keeps the legs under the body
  fade      crossfade ticks into this clip in the game
  samples   samples written to the game (0: 24 for a cycle, 32 for a loop,
            one per tick up to 31 for once)
  emote     true: players can play it with @e NAME
  mask      joints this clip sets when it is layered (empty: all)
  notes     free text
  keys      [{t: 0..1, lift: px, ease, pose: {joint: [x, y, z]}}]; a joint
            left out of a pose is at rest (0, 0, 0)

Pose conventions (tc/rig.tc): angles in degrees, x + swings a limb forward /
tips the head up / leans the torso back; y + turns it to its left; z + tips
its top to its left (a right arm out to the side is z +, a left arm z -).
*Pos joints are pivot offsets in skin pixels in the torso frame (+X left, +Y
up, +Z forward): hipRPos / hipLPos y + lifts a leg, which reads as a bent
knee (R6 has none).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_fk  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CLIP_DIR = ROOT / "anim" / "clips"
OUT_TC = ROOT / "tc" / "anim_data.tc"

KINDS = ("cycle", "loop", "once")
EASES = ("smooth", "in", "out", "linear")


# ------------------------------------------------------------------ clips


def normalize(doc: dict) -> dict:
    """A clip document with every field present and checked; raises
    ValueError on a bad clip."""
    name = str(doc.get("name", ""))
    if not name or not all(c.isalnum() or c in "_-" for c in name) or len(name) > 32:
        raise ValueError("name: letters, digits, - and _ (at most 32)")
    kind = doc.get("kind", "once")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    length = float(doc.get("length", 10))
    if length <= 0:
        raise ValueError("length must be positive")
    interp = doc.get("interp", "ease")
    if interp not in ("spline", "ease"):
        raise ValueError("interp must be spline or ease")
    keys = []
    for k in doc.get("keys", []):
        t = float(k.get("t", 0))
        if not 0 <= t <= 1:
            raise ValueError("key t must be within 0..1")
        ease = k.get("ease", "smooth")
        if ease not in EASES:
            raise ValueError(f"key ease must be one of {EASES}")
        pose = {}
        for j, v in (k.get("pose") or {}).items():
            if j not in rig_fk.JOINTS:
                raise ValueError(f"unknown joint {j}")
            if len(v) != 3:
                raise ValueError(f"joint {j} needs 3 numbers")
            pose[j] = [float(x) for x in v]
        keys.append({"t": t, "lift": float(k.get("lift", 0)), "ease": ease, "pose": pose})
    if not keys:
        raise ValueError("a clip needs at least one key")
    keys.sort(key=lambda k: k["t"])
    if kind != "once" and keys[-1]["t"] >= 1:
        raise ValueError("a looping clip's keys must be before t = 1 (t = 1 is t = 0 again)")
    mask = [m for m in doc.get("mask", []) if m in rig_fk.JOINTS]
    return {
        "name": name, "kind": kind, "length": length, "interp": interp,
        "planted": bool(doc.get("planted", True)), "counter": bool(doc.get("counter", True)),
        "fade": max(1, int(doc.get("fade", 4))), "samples": max(0, int(doc.get("samples", 0))),
        "emote": bool(doc.get("emote", False)), "mask": mask, "notes": str(doc.get("notes", "")),
        "keys": keys,
    }


def num(v: float):
    r = round(float(v), 3)
    return int(r) if r == int(r) else r


def format_clip(doc: dict) -> str:
    """A clip as JSON: one field per line, one key per line (short diffs)."""
    head = {k: v for k, v in doc.items() if k != "keys"}
    lines = ["{"]
    for k, v in head.items():
        lines.append(f" {json.dumps(k)}: {json.dumps(num(v) if isinstance(v, float) else v)},")
    lines.append(' "keys": [')
    out = []
    for k in doc["keys"]:
        pose = {j: [num(x) for x in v] for j, v in k["pose"].items() if any(abs(x) > 1e-9 for x in v)}
        out.append("  " + json.dumps({"t": num(k["t"]), "lift": num(k["lift"]), "ease": k["ease"], "pose": pose}))
    lines.append(",\n".join(out))
    lines += [" ]", "}"]
    return "\n".join(lines) + "\n"


class Clip:
    """A loaded clip (see the module doc for the fields)."""

    def __init__(self, doc: dict):
        doc = normalize(doc)
        self.doc = doc
        for k, v in doc.items():
            setattr(self, k, v)

    def n(self) -> int:
        if self.samples:
            return self.samples
        if self.kind == "cycle":
            return 24
        if self.kind == "loop":
            return 32
        return min(int(self.length) + 1, 31)


def load_clips() -> list:
    return [Clip(json.loads(p.read_text())) for p in sorted(CLIP_DIR.glob("*.json"))]


def by_name() -> dict:
    return {c.name: c for c in load_clips()}


# ------------------------------------------------------------- sampling


def ease_fn(name: str, u: float) -> float:
    if name == "linear":
        return u
    if name == "in":
        return u * u
    if name == "out":
        return 1 - (1 - u) * (1 - u)
    return u * u * (3 - 2 * u)


def catmull(p0, p1, p2, p3, u):
    return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u + (-p0 + 3 * p1 - 3 * p2 + p3) * u * u * u)


def full_pose(k: dict) -> dict:
    pose = {j: (0.0, 0.0, 0.0) for j in rig_fk.JOINTS}
    for j, v in k["pose"].items():
        pose[j] = tuple(v)
    return pose


def raw_at(clip: Clip, t: float) -> tuple:
    """The interpolated (pose, lift) at time t, before post-processing.
    (tools/anim_editor/rig.js has the same code.)"""
    keys = [dict(k, full=full_pose(k)) for k in clip.keys]
    loop = clip.kind in ("cycle", "loop")
    if loop:
        t = t % 1.0
        n = len(keys)

        def shifted(i: int, dt: float) -> dict:
            k = keys[i % n]
            return dict(k, t=k["t"] + dt)

        ext = [shifted(n - 2, -1), shifted(n - 1, -1)] + keys + [shifted(0, 1), shifted(1, 1)]
    else:
        if t <= keys[0]["t"]:
            return dict(keys[0]["full"]), keys[0]["lift"]
        if t >= keys[-1]["t"]:
            return dict(keys[-1]["full"]), keys[-1]["lift"]
        ext = keys
    i = max(i for i in range(len(ext) - 1) if ext[i]["t"] <= t)
    a, b = ext[i], ext[i + 1]
    u = 0.0 if b["t"] == a["t"] else (t - a["t"]) / (b["t"] - a["t"])
    p0 = ext[i - 1] if i > 0 else a
    p3 = ext[i + 2] if i + 2 < len(ext) else b

    def mix(va, vb, v0, v3):
        if clip.interp == "spline":
            return catmull(v0, va, vb, v3, u)
        return va + (vb - va) * ease_fn(b["ease"], u)

    pose = {}
    for j in rig_fk.JOINTS:
        pose[j] = tuple(mix(a["full"][j][c], b["full"][j][c], p0["full"][j][c], p3["full"][j][c]) for c in range(3))
    return pose, mix(a["lift"], b["lift"], p0["lift"], p3["lift"])


def pose_at(clip: Clip, t: float) -> dict:
    """The final pose at time t (0..1): interpolated and post-processed."""
    pose, lift = raw_at(clip, t)
    if clip.counter:
        r = pose["root"]
        for h in ("hipR", "hipL"):
            pose[h] = rig_fk.sub(pose[h], r)
    x, y, z = pose["rootPos"]
    if clip.planted:
        low = min(rig_fk.foot_low(pose, "legR")[1], rig_fk.foot_low(pose, "legL")[1])
        pose["rootPos"] = (x, y - low + lift, z)
    else:
        pose["rootPos"] = (x, y + lift, z)
    return pose


def sample_times(clip: Clip) -> list:
    n = clip.n()
    if clip.kind in ("cycle", "loop"):
        return [i / n for i in range(n)]
    if n == 1:
        return [0.0]
    return [i / (n - 1) for i in range(n)]


def samples(clip: Clip) -> list:
    return [pose_at(clip, t) for t in sample_times(clip)]


# ---------------------------------------------------------------- output


def fmt(v: float) -> str:
    r = round(v, 2)
    if r == int(r):
        return str(int(r))
    return f"{r:g}"


def clip_string(clip: Clip) -> str:
    vals = []
    for pose in samples(clip):
        for j in rig_fk.JOINTS:
            vals.extend(fmt(c) for c in pose[j])
    return ",".join(vals)


KIND = {"once": 0, "loop": 1, "cycle": 2}


def write_tc(clips: list | None = None) -> str:
    """Writes tc/anim_data.tc from the clips; returns the data version."""
    clips = clips if clips is not None else load_clips()
    strs = {c.name: clip_string(c) for c in clips}
    emotes = [c.name for c in clips if c.emote]
    ver = hashlib.sha1(("|".join(f"{k}={v}" for k, v in strs.items()) + "|" + ",".join(emotes)).encode()).hexdigest()[:10]
    lines = [
        "// Generated by tools/anim_clips.py from anim/clips/*.json: do not edit",
        "// (edit the clips with tools/anim_editor).",
        "",
        "/** Per clip: the samples as text, flattened (samples x 12 joints x 3),",
        " * joints in animJoints() order; parsed into animData on first use. */",
        "declare global animStr: dict[str];",
        "declare global animData: dict[list];",
        "/** Per clip: [samples, kind (0 once, 1 loop over ticks, 2 cycle over",
        " * blocks), length (ticks or blocks per cycle), fade-in ticks]. */",
        "declare global animMeta: dict[list];",
        "/** Per clip: the joints it sets ([] all). */",
        "declare global animMask: dict[list];",
        "/** Version of the loaded clip data. */",
        "declare global animVer: str;",
        "",
        "/** Version of the clip data in this code. */",
        "function animVersion(): str {",
        f'    return "{ver}";',
        "}",
        "",
        "/** The joints in a sample, in order. */",
        "function animJoints(): list {",
        "    return [" + ", ".join(f'"{j}"' for j in rig_fk.JOINTS) + "];",
        "}",
        "",
        "/** The clips players can play with @e NAME. */",
        "function animEmotes(): list {",
        "    return [" + ", ".join(f'"{e}"' for e in emotes) + "];",
        "}",
        "",
        "/** Loads every clip (split over small functions: DiamondFire cannot",
        " * replace a very large code line). */",
        "function loadClips {",
        "    global animStr = {};",
        "    global animData = {};",
        "    global animMeta = {};",
        "    global animMask = {};",
        "    global animVer = animVersion();",
    ]
    groups = [clips[i:i + 2] for i in range(0, len(clips), 2)]
    for gi in range(len(groups)):
        lines.append(f"    clips{gi + 1}();")
    lines += ["}", ""]
    for gi, group in enumerate(groups):
        lines.append(f"function clips{gi + 1} {{")
        for c in group:
            lines.append(f'    global animStr["{c.name}"] = "{strs[c.name]}";')
            lines.append(f'    global animMeta["{c.name}"] = [{c.n()}, {KIND[c.kind]}, {fmt(c.length)}, {c.fade}];')
            mask = ", ".join(f'"{m}"' for m in c.mask)
            lines.append(f'    global animMask["{c.name}"] = [{mask}];')
        lines += ["}", ""]
    OUT_TC.write_text("\n".join(lines))
    return ver


if __name__ == "__main__":
    clips = load_clips()
    ver = write_tc(clips)
    longest = max(len(clip_string(c)) for c in clips)
    print(f"wrote {OUT_TC.relative_to(ROOT)} ({len(clips)} clips, version {ver}, longest string {longest} chars)")
