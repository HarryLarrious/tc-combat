#!/usr/bin/env python3
"""Renders animation clips to contact sheets (PNG), to see them without the
game.

    python3 tools/anim_preview.py              every clip
    python3 tools/anim_preview.py walk run     some clips
    python3 tools/anim_preview.py run --frames 16

Writes build/anim_preview/<clip>.png. Each sheet has:
  - a header: clip name, kind and length, key times, notes; for cycles,
    how far each foot slides while it is on the ground ("slip")
  - three rows of frames over the clip: side (from the model's right,
    facing right), front, and three-quarter. Frames on a key are marked
    with a gold border and the key time.
  - side row of a cycle: the ground scrolls by the distance walked, so a
    planted foot should stay on the same ground mark
  - for cycles: a chart of each foot's height and its position along the
    ground over the cycle (red right foot, blue left foot)

The poses are the clip samples written to the game (tools/anim_clips.py),
put through the same rig math (tools/rig_fk.py), with the head looking
straight ahead as the game does (the neck turns back against the torso).
Colors: yellow head and arms, blue torso, green legs; the right arm and leg
are darker than the left. The face marks the front.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anim_clips  # noqa: E402
import rig_fk  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "anim_preview"
PX_PER_BLOCK = 1 / 0.05625  # skin pixels per block

S = 5           # screen pixels per skin pixel
CW, CH = 170, 250   # cell size
GROUND = CH - 34
HEADER = 74
BG = (236, 238, 242)
INK = (30, 32, 38)
DIM = (120, 124, 132)
GOLD = (214, 160, 20)

COLORS = {
    "head": (245, 205, 48), "torso": (13, 105, 172),
    "armR": (214, 172, 30), "armL": (255, 226, 112),
    "legR": (118, 150, 44), "legL": (172, 204, 92),
}
LIGHT = (0.35, 0.8, 0.48)

VIEWS = [("side", 90.0), ("front", 0.0), ("3/4", 40.0)]

FACES = [  # corner index quads of a box (see rig_fk.corners order)
    (0, 1, 3, 2), (4, 6, 7, 5),  # -x, +x
    (0, 4, 5, 1), (2, 3, 7, 6),  # -y, +y
    (0, 2, 6, 4), (1, 5, 7, 3),  # -z, +z
]


def font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


F_HEAD = font(17)
F_CELL = font(12)
F_SMALL = font(11)


def norm(v):
    m = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) or 1
    return (v[0] / m, v[1] / m, v[2] / m)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def camera(angle: float):
    """(toward camera d, screen right r) for a camera `angle` degrees from
    the front toward the model's right side."""
    a = math.radians(angle)
    d = (-math.sin(a), 0.0, math.cos(a))
    r = cross((0.0, 1.0, 0.0), d)
    return d, r


def look_ahead(pose: dict) -> dict:
    """The neck turned back against the torso, as the game's head look does
    when the player looks straight ahead."""
    p = dict(pose)
    r = pose["root"]

    def wrap(a):
        return (a + 180.0) % 360.0 - 180.0

    nx = max(-50.0, min(60.0, -wrap(r[0])))
    ny = max(-70.0, min(70.0, -wrap(r[1])))
    n = pose["neck"]
    p["neck"] = (n[0] + nx, n[1] + ny, n[2])
    return p


def draw_model(img: ImageDraw.ImageDraw, pose: dict, angle: float, ox: float, oy: float, shift_z: float = 0.0):
    """Draws the model with its origin (ground between the feet) at screen
    (ox, oy). shift_z moves the ground marks only (see draw_ground)."""
    d, r = camera(angle)

    def proj(p):
        return (ox + dot(p, r) * S, oy - p[1] * S)

    faces = []
    for name, c, B, size in rig_fk.parts(pose):
        cs = rig_fk.corners(c, B, size)
        base = COLORS[name]
        for quad in FACES:
            pts = [cs[i] for i in quad]
            n = norm(cross(rig_fk.sub(pts[1], pts[0]), rig_fk.sub(pts[3], pts[0])))
            center = rig_fk.mul(rig_fk.add(rig_fk.add(pts[0], pts[1]), rig_fk.add(pts[2], pts[3])), 0.25)
            # outward normal: away from the box center
            if dot(n, rig_fk.sub(center, c)) < 0:
                n = rig_fk.mul(n, -1)
            if dot(n, d) <= 0.001:
                continue
            shade = 0.58 + 0.42 * max(0.0, dot(n, norm(LIGHT)))
            col = tuple(min(255, int(ch * shade)) for ch in base)
            faces.append((dot(center, d), [proj(p) for p in pts], col, name, n, B, c))
    faces.sort(key=lambda f: f[0])
    for depth, pts, col, name, n, B, c in faces:
        img.polygon(pts, fill=col, outline=(40, 40, 48))
        if name == "head" and dot(n, B[2]) > 0.9:
            # the face: two eyes and a mouth on the front
            for ex in (-1.6, 1.6):
                quad = [rig_fk.add(c, rig_fk.at(B, (ex + dx, 0.6 + dy, 4.02))) for dx, dy in ((-0.5, -0.8), (0.5, -0.8), (0.5, 0.8), (-0.5, 0.8))]
                img.polygon([proj(p) for p in quad], fill=(30, 30, 30))
            quad = [rig_fk.add(c, rig_fk.at(B, p)) for p in ((-1.6, -1.8, 4.02), (1.6, -1.8, 4.02), (1.6, -1.2, 4.02), (-1.6, -1.2, 4.02))]
            img.polygon([proj(p) for p in quad], fill=(30, 30, 30))


def draw_ground(img: ImageDraw.ImageDraw, x0: float, oy: float, angle: float, travel_px: float):
    """The ground line, with marks every 4 skin pixels that scroll back by
    travel_px (side view of a cycle)."""
    img.line([(x0 + 4, oy), (x0 + CW - 4, oy)], fill=(90, 94, 100), width=2)
    if angle != 90.0:
        return
    step = 4 * S
    off = (-travel_px * S) % step
    x = x0 + 4 + off
    while x < x0 + CW - 4:
        img.line([(x, oy), (x, oy + 6)], fill=(90, 94, 100), width=1)
        x += step


def frame_times(clip: anim_clips.Clip, frames: int) -> list:
    if clip.kind in ("cycle", "loop"):
        return [i / frames for i in range(frames)]
    n = min(frames, int(clip.length) + 1)
    return [i / (n - 1) for i in range(n)] if n > 1 else [0.0]


def key_near(clip, t: float, half: float):
    for k in clip.keys:
        if abs(k.t - t) <= half + 1e-9:
            return k.t
    return None


def time_label(clip, t: float) -> str:
    if clip.kind == "cycle":
        return f"{t * 100:.0f}% · {t * clip.length:.2f} bl"
    return f"tick {t * clip.length:.1f}"


def foot_track(clip, steps: int = 96):
    """Per foot: [(t, height, along-ground position in px)] over the cycle,
    in the ground frame (the body moves forward by the cycle's length)."""
    out = {"legR": [], "legL": []}
    for i in range(steps + 1):
        t = i / steps
        pose = anim_clips.pose_at(clip, t)
        travel = t * clip.length * PX_PER_BLOCK
        for leg in out:
            p = rig_fk.foot_low(pose, leg)
            out[leg].append((t, p[1], p[2] + travel))
    return out


def slip(track) -> float:
    """Largest slide of a foot along the ground while it touches (height
    under 0.3 px), over each contiguous contact."""
    worst = 0.0
    run = []
    for t, h, z in track + [(None, 99, 0)]:
        if h < 0.3:
            run.append(z)
        else:
            if len(run) > 1:
                worst = max(worst, max(run) - min(run))
            run = []
    return worst


def draw_chart(img: ImageDraw.ImageDraw, x0: int, y0: int, w: int, h: int, clip):
    tr = foot_track(clip)
    img.rectangle([x0, y0, x0 + w, y0 + h], outline=(180, 184, 190))
    half = h // 2 - 6
    img.text((x0 + 6, y0 + 4), "foot height (px)", fill=DIM, font=F_SMALL)
    img.text((x0 + 6, y0 + half + 10), "foot along ground (px, ground frame)", fill=DIM, font=F_SMALL)
    hmax = max(4.0, max(p[1] for leg in tr.values() for p in leg))
    zs = [p[2] for leg in tr.values() for p in leg]
    zmin, zmax = min(zs), max(zs)
    for leg, col in (("legR", (200, 50, 50)), ("legL", (40, 90, 210))):
        pts_h = [(x0 + 8 + t * (w - 16), y0 + half - 2 - (hh / hmax) * (half - 22)) for t, hh, z in tr[leg]]
        pts_z = [(x0 + 8 + t * (w - 16), y0 + h - 6 - (z - zmin) / max(1e-6, zmax - zmin) * (half - 24)) for t, hh, z in tr[leg]]
        img.line(pts_h, fill=col, width=2)
        img.line(pts_z, fill=col, width=2)
    for k in clip.keys:
        x = x0 + 8 + k.t * (w - 16)
        img.line([(x, y0 + 18), (x, y0 + h - 4)], fill=(225, 205, 140), width=1)
    return slip(tr["legR"]), slip(tr["legL"])


def render(clip, frames: int) -> Path:
    times = frame_times(clip, frames)
    cols = len(times)
    chart_h = 150 if clip.kind == "cycle" else 0
    W = max(cols * CW, 700)
    H = HEADER + len(VIEWS) * CH + chart_h + 10
    im = Image.new("RGB", (W, H), BG)
    g = ImageDraw.Draw(im)

    keys = ", ".join(f"{k.t:g}" for k in sorted(clip.keys, key=lambda k: k.t))
    unit = "blocks/cycle" if clip.kind == "cycle" else "ticks"
    flags = [clip.interp]
    if clip.planted:
        flags.append("planted")
    if clip.counter:
        flags.append("counter")
    g.text((10, 8), f"{clip.name}", fill=INK, font=F_HEAD)
    g.text((10 + 12 * len(clip.name) + 20, 11), f"{clip.kind} · {clip.length:g} {unit} · fade {clip.fade} · {' · '.join(flags)} · keys at {keys}", fill=DIM, font=F_SMALL)
    if clip.notes:
        g.text((10, 32), clip.notes, fill=INK, font=F_SMALL)

    half = 0.5 / max(1, cols) if clip.kind != "once" else 0.5 / max(1, cols - 1)
    for vi, (vname, angle) in enumerate(VIEWS):
        y = HEADER + vi * CH
        g.text((6, y + 4), vname, fill=DIM, font=F_CELL)
        for ci, t in enumerate(times):
            x = ci * CW
            pose = look_ahead(anim_clips.pose_at(clip, t))
            travel = t * clip.length * PX_PER_BLOCK if clip.kind == "cycle" else 0.0
            draw_ground(g, x, y + GROUND, angle, travel)
            draw_model(g, pose, angle, x + CW / 2, y + GROUND)
            kt = key_near(clip, t, half)
            if kt is not None:
                g.rectangle([x + 2, y + 2, x + CW - 3, y + CH - 3], outline=GOLD, width=2)
            if vi == 0:
                lab = time_label(clip, t) + (f"  key {kt:g}" if kt is not None else "")
                g.text((x + 8, y + CH - 26), lab, fill=INK, font=F_CELL)
    if clip.kind == "cycle":
        sr, sl = draw_chart(g, 10, HEADER + len(VIEWS) * CH, W - 20, chart_h, clip)
        g.text((10, 52), f"foot slip while on the ground: right {sr:.1f} px, left {sl:.1f} px "
                         f"(a step covers {clip.length * PX_PER_BLOCK / 2:.0f} px)", fill=INK, font=F_SMALL)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{clip.name}.png"
    im.save(path)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="*", help="clip names (default: all)")
    ap.add_argument("--frames", type=int, default=12, help="frames per sheet (once clips: at most one per tick)")
    args = ap.parse_args()
    names = args.clips or [c.name for c in anim_clips.CLIPS]
    for n in names:
        if n not in anim_clips.BY_NAME:
            sys.exit(f"unknown clip {n}; clips: {', '.join(anim_clips.BY_NAME)}")
        print(render(anim_clips.BY_NAME[n], args.frames).relative_to(ROOT))


if __name__ == "__main__":
    main()
