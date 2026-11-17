#!/usr/bin/env python3
"""Animation clips for the player rig: the one source of every animation.

    python3 tools/anim_clips.py          writes tc/anim_data.tc
    python3 tools/anim_preview.py ...    renders the same samples to images

A clip is a few key poses on a timeline (t from 0 to 1). Poses use the
rig's joints and conventions (tc/rig.tc):
  angles  x + swings a limb forward / tips the head up / leans the torso
          back; y + turns it to its left; z + tips its top to its left (for
          a right arm, z + raises it out to the side; left arm, z -)
  *Pos    a pivot offset in skin pixels, torso frame (+X left, +Y up, +Z
          forward). hipRPos / hipLPos y + lifts a leg: R6 has no knees, so
          lifting the swinging leg is what reads as a bent knee.
  lift    extra height (px) on top of the ground contact (flight, hops)

Clip kinds: "cycle" loops over distance walked (length = blocks per
cycle), "loop" loops over time (length = ticks), "once" plays once over
time (length = ticks) and holds its last pose.

Interpolation: "spline" (Catmull-Rom through the keys, smooth arcs, for
cycles) or "ease" (each key sets how the motion arrives at it: "smooth"
eases in and out, "in" accelerates into it (a strike), "out" decelerates
into it (a wind-up or a settle), "linear").

Post-processing per sample:
  counter  the legs turn back against the torso's angles, so leaning or
           twisting the torso keeps the legs under the body
  planted  the root is raised or lowered so the lowest foot touches the
           ground (then `lift` is added): feet never sink or float
"""

from __future__ import annotations

import hashlib
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_fk  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_TC = ROOT / "tc" / "anim_data.tc"

V = tuple


# ------------------------------------------------------------------ keys


@dataclass
class Key:
    t: float
    pose: dict
    lift: float = 0.0
    ease: str = "smooth"


def K(t: float, *bases: dict, lift: float = 0.0, ease: str = "smooth", **joints) -> Key:
    """A key at time t: the rest pose, then each base pose, then joints."""
    pose = rig_fk.rest()
    for b in bases:
        pose.update(b)
    for j, v in joints.items():
        if j not in pose:
            raise KeyError(f"unknown joint {j}")
        pose[j] = tuple(float(x) for x in v)
    return Key(t, pose, lift, ease)


SWAP = {"shoulderR": "shoulderL", "shoulderL": "shoulderR", "hipR": "hipL", "hipL": "hipR",
        "shoulderRPos": "shoulderLPos", "shoulderLPos": "shoulderRPos", "hipRPos": "hipLPos", "hipLPos": "hipRPos"}


def mirror_pose(pose: dict) -> dict:
    """The pose mirrored left to right: sides swap, y and z angles and x
    offsets flip."""
    out = {}
    for j, (x, y, z) in pose.items():
        dst = SWAP.get(j, j)
        if j.endswith("Pos"):
            out[dst] = (-x, y, z)
        else:
            out[dst] = (x, -y, -z)
    return out


def mirror(k: Key, t: float) -> Key:
    return Key(t, mirror_pose(k.pose), k.lift, k.ease)


@dataclass
class Clip:
    name: str
    kind: str          # cycle | loop | once
    length: float      # blocks per cycle (cycle) or ticks
    keys: list
    interp: str = "spline"
    planted: bool = True
    counter: bool = True
    fade: int = 4      # crossfade ticks into this clip
    samples: int = 0   # 0: chosen from the kind
    notes: str = ""
    mask: list = field(default_factory=list)  # joints this clip sets (empty: all)

    def n(self) -> int:
        if self.samples:
            return self.samples
        if self.kind == "cycle":
            return 24
        if self.kind == "loop":
            return 32
        return min(int(self.length) + 1, 31)


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


def raw_at(clip: Clip, t: float) -> tuple:
    """The interpolated (pose, lift) at time t, before post-processing."""
    keys = sorted(clip.keys, key=lambda k: k.t)
    loop = clip.kind in ("cycle", "loop")
    if loop:
        t = t % 1.0
    # the segment [a, b] holding t, with neighbours for the spline
    ext = list(keys)
    if loop:
        n = len(keys)

        def shifted(i: int, dt: float) -> Key:
            k = keys[i % n]
            return Key(k.t + dt, k.pose, k.lift, k.ease)

        ext = [shifted(n - 2, -1), shifted(n - 1, -1)] + keys + [shifted(0, 1), shifted(1, 1)]
    else:
        if t <= keys[0].t:
            return dict(keys[0].pose), keys[0].lift
        if t >= keys[-1].t:
            return dict(keys[-1].pose), keys[-1].lift
    i = max(i for i in range(len(ext) - 1) if ext[i].t <= t)
    a, b = ext[i], ext[i + 1]
    u = 0.0 if b.t == a.t else (t - a.t) / (b.t - a.t)
    p0 = ext[i - 1] if i > 0 else a
    p3 = ext[i + 2] if i + 2 < len(ext) else b

    def mix(va, vb, v0, v3):
        if clip.interp == "spline":
            return catmull(v0, va, vb, v3, u)
        e = ease_fn(b.ease, u)
        return va + (vb - va) * e

    pose = {}
    for j in rig_fk.JOINTS:
        pose[j] = tuple(mix(a.pose[j][c], b.pose[j][c], p0.pose[j][c], p3.pose[j][c]) for c in range(3))
    lift = mix(a.lift, b.lift, p0.lift, p3.lift)
    return pose, lift


def pose_at(clip: Clip, t: float) -> dict:
    """The final pose at time t (0..1): interpolated and post-processed."""
    pose, lift = raw_at(clip, t)
    if clip.counter:
        r = pose["root"]
        for h in ("hipR", "hipL"):
            pose[h] = rig_fk.sub(pose[h], r)
    if clip.planted:
        low = min(rig_fk.foot_low(pose, "legR")[1], rig_fk.foot_low(pose, "legL")[1])
        x, y, z = pose["rootPos"]
        pose["rootPos"] = (x, y - low + lift, z)
    else:
        x, y, z = pose["rootPos"]
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


# ----------------------------------------------------------------- clips
#
# Every clip says what it is for, its key poses, and why it reads.

IDLE_BASE = dict(shoulderR=(2, 0, 4), shoulderL=(2, 0, -4), hipR=(0, 0, 2), hipL=(0, 0, -2))

# Idle: breathing only. The chest rises (torso eases back 1.5 degrees) and
# the arms drift out a little on the in-breath; nothing leaves the body.
IDLE = Clip("idle", "loop", 80, [
    K(0.0, IDLE_BASE),
    K(0.5, IDLE_BASE, root=(1.5, 0, 0), shoulderR=(4, 0, 7), shoulderL=(4, 0, -7)),
], fade=6, notes="breath out at 0, in at 0.5")

# Walk: contact (legs split, arms opposite, torso twisted with the forward
# arm) -> passing (stance leg under the body, swing leg lifted so it clears
# the ground). The root is lowest at contact and highest at passing, which
# is the bob; planting keeps the stance foot on the ground.
WALK_CONTACT = K(0.0, hipR=(38, 0, 0), hipL=(-36, 0, 0),
                 shoulderR=(-26, 0, 5), shoulderL=(32, 0, -5), root=(-4, -7, 0))
WALK_PASS = K(0.25, hipR=(-2, 0, 0), hipL=(12, 0, 0), hipLPos=(0, 2.0, 0.3),
              shoulderR=(0, 0, 5), shoulderL=(6, 0, -5), root=(-5, 0, -1.5))
WALK = Clip("walk", "cycle", 1.7, [WALK_CONTACT, WALK_PASS, mirror(WALK_CONTACT, 0.5), mirror(WALK_PASS, 0.75)],
            fade=5, notes="R contact 0, passing 0.25, L contact 0.5, passing 0.75")

# Run: contact -> down (stance leg under the body, the other knee driving
# forward and up) -> push-off (stance leg drives back, knee high in front)
# -> flight (both feet off, the back leg kicking up behind). Strong forward
# lean; the arms pump further forward than back, the torso twisting with
# them.
RUN_CONTACT = K(0.0, hipR=(36, 0, 0), hipL=(-30, 0, 0), hipLPos=(0, 2.2, -0.6),
                shoulderR=(-30, 0, 12), shoulderL=(45, 0, -12), root=(-14, -10, 0))
RUN_DOWN = K(0.125, hipR=(6, 0, 0), hipL=(20, 0, 0), hipLPos=(0, 2.8, 0.6),
             shoulderR=(-5, 0, 12), shoulderL=(25, 0, -12), root=(-16, -3, 0))
RUN_PUSH = K(0.25, hipR=(-30, 0, 0), hipL=(55, 0, 0), hipLPos=(0, 2.6, 1.2),
             shoulderR=(42, 0, 12), shoulderL=(-28, 0, -12), root=(-13, 9, 0))
RUN_FLIGHT = K(0.375, hipR=(-55, 0, 0), hipRPos=(0, 2.6, -0.4), hipL=(32, 0, 0), hipLPos=(0, 0.8, 0.3),
               shoulderR=(46, 0, 12), shoulderL=(-32, 0, -12), root=(-12, 10, 0), lift=1.6)
RUN = Clip("run", "cycle", 2.8, [RUN_CONTACT, RUN_DOWN, RUN_PUSH, RUN_FLIGHT,
                                  mirror(RUN_CONTACT, 0.5), mirror(RUN_DOWN, 0.625), mirror(RUN_PUSH, 0.75), mirror(RUN_FLIGHT, 0.875)],
           fade=4, notes="R contact 0, down .125, push .25, flight .375; L from .5")

# Crouch: torso leaned in, arms forward, short steps.
CROUCH_BASE = dict(root=(-22, 0, 0), shoulderR=(30, 0, 10), shoulderL=(30, 0, -10))
CROUCH_IDLE = Clip("crouchIdle", "loop", 60, [
    K(0.0, CROUCH_BASE, hipR=(10, 0, 4), hipL=(-8, 0, -4)),
    K(0.5, CROUCH_BASE, hipR=(10, 0, 4), hipL=(-8, 0, -4), root=(-20, 0, 0), shoulderR=(33, 0, 12), shoulderL=(33, 0, -12)),
], fade=5)
CROUCH_CONTACT = K(0.0, CROUCH_BASE, hipR=(22, 0, 0), hipL=(-20, 0, 0), shoulderR=(18, 0, 10), shoulderL=(42, 0, -10), root=(-22, -4, 0))
CROUCH_PASS = K(0.25, CROUCH_BASE, hipR=(0, 0, 0), hipL=(4, 0, 0), hipLPos=(0, 1.2, 0))
CROUCH = Clip("crouch", "cycle", 1.3, [CROUCH_CONTACT, CROUCH_PASS, mirror(CROUCH_CONTACT, 0.5), mirror(CROUCH_PASS, 0.75)], fade=5)

# Combat stance (holding an item, standing): side-on (torso turned right,
# left shoulder leading), feet staggered, weapon arm forward and low, the
# free arm up in front. Breathing.
STANCE_BASE = dict(root=(-6, -25, 0), hipR=(-10, 0, 5), hipL=(14, 0, -4),
                   shoulderR=(35, 0, 12), shoulderL=(25, 0, -12))
STANCE = Clip("stance", "loop", 60, [
    K(0.0, STANCE_BASE),
    K(0.5, STANCE_BASE, root=(-4, -25, 0), shoulderR=(39, 0, 13), shoulderL=(29, 0, -13)),
], fade=5)

# The weapon arm while walking with an item (sets only that arm).
HOLD = Clip("hold", "loop", 1, [K(0.0, shoulderR=(40, 0, 12))], samples=1,
            mask=["shoulderR", "shoulderRPos"])

# Jump: arms swing up as the body leaves the ground, one knee tucks.
JUMP = Clip("jump", "once", 8, [
    K(0.0, shoulderR=(40, 0, 12), shoulderL=(40, 0, -12), root=(-6, 0, 0)),
    K(0.4, hipR=(55, 0, 0), hipRPos=(0, 2.2, 0.5), hipL=(20, 0, 0), hipLPos=(0, 1, 0),
      shoulderR=(150, 0, 25), shoulderL=(150, 0, -25), root=(6, 0, 0), ease="out"),
    K(1.0, hipR=(40, 0, 0), hipRPos=(0, 1.6, 0.3), hipL=(12, 0, 0), hipLPos=(0, 0.6, 0),
      shoulderR=(140, 0, 30), shoulderL=(140, 0, -30), root=(4, 0, 0)),
], interp="ease", planted=False, fade=2)

# Fall: arms up and out for balance, legs apart, a slow alternating flutter.
FALL = Clip("fall", "loop", 16, [
    K(0.0, shoulderR=(35, 0, 70), shoulderL=(45, 0, -62), hipR=(18, 0, 4), hipL=(-10, 0, -4), root=(-4, 0, 0)),
    K(0.5, shoulderR=(45, 0, 62), shoulderL=(35, 0, -70), hipR=(-8, 0, 4), hipL=(16, 0, -4), root=(-4, 0, 0)),
], planted=False, fade=5)

# Land: impact absorbed by a forward lean and split legs, arms out, then
# recover to idle.
LAND = Clip("land", "once", 7, [
    K(0.0, root=(-16, 0, 0), hipR=(24, 0, 6), hipL=(-18, 0, -6), shoulderR=(-8, 0, 28), shoulderL=(-8, 0, -28)),
    K(0.35, root=(-10, 0, 0), hipR=(16, 0, 5), hipL=(-12, 0, -5), shoulderR=(-4, 0, 18), shoulderL=(-4, 0, -18), ease="out"),
    K(1.0, IDLE_BASE),
], interp="ease", fade=1)

# Running jump: a tucked front flip.
FLIP_TUCK = dict(hipR=(95, 0, 4), hipRPos=(0, 2.5, 1), hipL=(95, 0, -4), hipLPos=(0, 2.5, 1),
                 shoulderR=(70, 0, 15), shoulderL=(70, 0, -15))
FLIP = Clip("flip", "once", 12, [
    K(0.0, shoulderR=(60, 0, 12), shoulderL=(60, 0, -12), root=(-10, 0, 0)),
    K(0.15, FLIP_TUCK, root=(-40, 0, 0), ease="in"),
    K(0.85, FLIP_TUCK, root=(-330, 0, 0), ease="linear"),
    K(1.0, hipR=(15, 0, 0), hipL=(5, 0, 0), shoulderR=(80, 0, 30), shoulderL=(80, 0, -30), root=(-360, 0, 0), ease="out"),
], interp="ease", planted=False, counter=False, fade=2)

# Weapon combo. Each hit: wind-up (decelerating into it, "out"), strike
# (accelerating, "in"), follow-through, recover. The torso leads the arm.
W_READY = dict(root=(-6, -15, 0), shoulderR=(40, 0, 12), shoulderL=(25, 0, -12), hipR=(-8, 0, 0), hipL=(10, 0, 0))
W1 = Clip("w1", "once", 11, [
    K(0.0, W_READY),
    K(0.3, root=(-6, -45, 0), shoulderR=(100, -95, 0), shoulderRPos=(-1, 1, -1), shoulderL=(50, 0, -25),
      hipR=(-12, 0, 0), hipL=(14, 0, 0), ease="out"),
    K(0.5, root=(-14, 45, 0), rootPos=(0, 0, 2.5), shoulderR=(100, 100, 0), shoulderRPos=(0, 0.5, 2),
      shoulderL=(25, 0, -55), hipR=(-22, 0, 0), hipL=(26, 0, 0), ease="in"),
    K(0.75, root=(-12, 55, 0), rootPos=(0, 0, 2.5), shoulderR=(80, 120, 10), shoulderL=(15, 0, -50),
      hipR=(-22, 0, 0), hipL=(26, 0, 0), ease="out"),
    K(1.0, root=(-8, 20, 0), rootPos=(0, 0, 1.5), shoulderR=(55, 40, 10), shoulderL=(25, 0, -20),
      hipR=(-8, 0, 0), hipL=(10, 0, 0)),
], interp="ease", fade=2)
W2 = Clip("w2", "once", 11, [
    K(0.0, W_READY),
    K(0.3, root=(-6, 40, 0), shoulderR=(100, 90, 0), shoulderRPos=(1, 1, 0), shoulderL=(30, 0, -40),
      hipR=(-12, 0, 0), hipL=(14, 0, 0), ease="out"),
    K(0.5, root=(-14, -45, 0), rootPos=(0, 0, 2.5), shoulderR=(95, -110, 0), shoulderRPos=(-1, 0.5, 2),
      shoulderL=(45, 0, -20), hipR=(-22, 0, 0), hipL=(26, 0, 0), ease="in"),
    K(0.75, root=(-12, -55, 0), rootPos=(0, 0, 2.5), shoulderR=(80, -125, 10), shoulderL=(40, 0, -15),
      hipR=(-22, 0, 0), hipL=(26, 0, 0), ease="out"),
    K(1.0, root=(-8, -20, 0), rootPos=(0, 0, 1.5), shoulderR=(55, -40, 10), shoulderL=(25, 0, -20),
      hipR=(-8, 0, 0), hipL=(10, 0, 0)),
], interp="ease", fade=2)
# Spinning slash: crouch and coil, hop into a full turn with both arms out,
# land and cut down. The legs turn with the body (no counter).
W3 = Clip("w3", "once", 16, [
    K(0.0, W_READY),
    K(0.2, root=(-12, -40, 0), shoulderR=(40, -40, 60), shoulderL=(40, 40, -60), hipR=(20, 0, 0), hipL=(-20, 0, 0), ease="out"),
    K(0.35, root=(-5, 60, 0), shoulderR=(0, 0, 95), shoulderRPos=(-1, 1, 0), shoulderL=(0, 0, -95),
      hipR=(30, 0, 0), hipL=(10, 0, 0), lift=2.5, ease="in"),
    K(0.6, root=(-5, 300, 0), shoulderR=(0, 0, 95), shoulderRPos=(-1, 1, 0), shoulderL=(0, 0, -95),
      hipR=(30, 0, 0), hipL=(10, 0, 0), lift=2.5, ease="linear"),
    K(0.75, root=(-25, 360, 0), rootPos=(0, 0, 2), shoulderR=(-15, 0, 10), shoulderRPos=(0, 0, 2),
      shoulderL=(-40, 0, -45), hipR=(-25, 0, 0), hipL=(35, 0, 0), ease="in"),
    K(1.0, root=(-12, 360, 0), rootPos=(0, 0, 1), shoulderR=(25, 0, 10), shoulderL=(10, 0, -20),
      hipR=(-10, 0, 0), hipL=(15, 0, 0), ease="out"),
], interp="ease", counter=False, fade=2)

# Fist combo: guard up, the punching shoulder turns into the jab, the fist
# extends past arm's length on impact and snaps back.
F_GUARD = dict(root=(-8, -15, 0), shoulderR=(75, 10, 15), shoulderL=(80, -10, -15), hipR=(-8, 0, 0), hipL=(10, 0, 0))
F1 = Clip("f1", "once", 8, [
    K(0.0, F_GUARD),
    K(0.25, F_GUARD, root=(-6, -28, 0), shoulderR=(65, 0, 15), shoulderRPos=(0, 0, -1), ease="out"),
    K(0.45, F_GUARD, root=(-12, 35, 0), rootPos=(0, 0, 1.5), shoulderR=(92, 12, 0), shoulderRPos=(0.5, 0, 3.5),
      shoulderL=(80, -10, -20), ease="in"),
    K(1.0, F_GUARD, ease="out"),
], interp="ease", fade=2)
F2 = Clip("f2", "once", 8, [mirror(k, k.t) for k in F1.keys], interp="ease", fade=2)
# Uppercut: dip low, launch up with the fist over the head, land in guard.
F3 = Clip("f3", "once", 13, [
    K(0.0, F_GUARD),
    K(0.3, root=(-22, -30, 0), shoulderR=(-30, 0, 20), shoulderL=(70, 0, -20), hipR=(24, 0, 0), hipL=(-20, 0, 0), ease="out"),
    K(0.5, root=(10, 30, 0), shoulderR=(175, 12, 0), shoulderRPos=(0, 2.5, 1), shoulderL=(-40, 0, -40),
      hipR=(-15, 0, 0), hipL=(45, 0, 0), hipLPos=(0, 1.5, 0), lift=3, ease="in"),
    K(0.7, root=(8, 30, 0), shoulderR=(170, 12, 0), shoulderRPos=(0, 2, 1), shoulderL=(-35, 0, -40),
      hipR=(-10, 0, 0), hipL=(35, 0, 0), hipLPos=(0, 1, 0), lift=3.5, ease="out"),
    K(1.0, F_GUARD),
], interp="ease", fade=2)

# Emotes.
WAVE = Clip("wave", "once", 60, [
    K(0.0, IDLE_BASE),
    K(0.12, shoulderR=(0, 0, 150), root=(0, 0, -4), neck=(0, 0, -8), shoulderL=(2, 0, -4), ease="out"),
    K(0.25, shoulderR=(0, 0, 170), root=(0, 0, -4), neck=(0, 0, -8), shoulderL=(2, 0, -4)),
    K(0.37, shoulderR=(0, 0, 135), root=(0, 0, -4), neck=(0, 0, -8), shoulderL=(2, 0, -4)),
    K(0.5, shoulderR=(0, 0, 170), root=(0, 0, -4), neck=(0, 0, -8), shoulderL=(2, 0, -4)),
    K(0.62, shoulderR=(0, 0, 135), root=(0, 0, -4), neck=(0, 0, -8), shoulderL=(2, 0, -4)),
    K(0.75, shoulderR=(0, 0, 165), root=(0, 0, -4), neck=(0, 0, -8), shoulderL=(2, 0, -4)),
    K(1.0, IDLE_BASE),
], interp="ease", fade=4)
POINT = Clip("point", "once", 40, [
    K(0.0, IDLE_BASE),
    K(0.2, shoulderR=(90, 5, 0), root=(-4, 20, 0), shoulderL=(-8, 0, -8), ease="out"),
    K(0.8, shoulderR=(88, 5, 0), root=(-4, 20, 0), shoulderL=(-8, 0, -8)),
    K(1.0, IDLE_BASE),
], interp="ease", fade=4)
CHEER_UP = dict(shoulderR=(170, 0, 25), shoulderL=(170, 0, -25))
CHEER = Clip("cheer", "once", 40, [
    K(0.0, IDLE_BASE),
    K(0.15, root=(-10, 0, 0), shoulderR=(-10, 0, 20), shoulderL=(-10, 0, -20), hipR=(10, 0, 4), hipL=(-8, 0, -4), ease="out"),
    K(0.3, CHEER_UP, lift=3, ease="out"),
    K(0.45, CHEER_UP, root=(-6, 0, 0), shoulderR=(150, 0, 30), shoulderL=(150, 0, -30), ease="in"),
    K(0.62, CHEER_UP, lift=3, ease="out"),
    K(0.8, CHEER_UP, root=(-6, 0, 0), ease="in"),
    K(1.0, IDLE_BASE),
], interp="ease", fade=3)
LAUGH_BASE = dict(shoulderR=(35, 0, -25), shoulderL=(35, 0, 25), neck=(20, 0, 0))
LAUGH = Clip("laugh", "once", 50, [K(0.0, IDLE_BASE)]
             + [K(0.1 + i * 0.1, LAUGH_BASE, root=(16 if i % 2 else 24, 0, 0)) for i in range(8)]
             + [K(1.0, IDLE_BASE)], interp="ease", fade=4)
DANCE_A = K(0.0, root=(-4, 20, 6), shoulderR=(20, 0, 120), shoulderL=(20, 0, -60), hipR=(15, 0, 6), hipL=(-5, 0, -4))
DANCE_B = K(0.25, root=(-8, 0, 0), shoulderR=(30, 0, 60), shoulderL=(30, 0, -60), hipR=(5, 0, 5), hipL=(5, 0, -5))
DANCE = Clip("dance", "loop", 40, [DANCE_A, DANCE_B, mirror(DANCE_A, 0.5), mirror(DANCE_B, 0.75)], fade=4)

CLIPS = [IDLE, WALK, RUN, CROUCH_IDLE, CROUCH, STANCE, HOLD, JUMP, FALL, LAND, FLIP,
         W1, W2, W3, F1, F2, F3, WAVE, POINT, CHEER, LAUGH, DANCE]
BY_NAME = {c.name: c for c in CLIPS}


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


def write_tc() -> str:
    strs = {c.name: clip_string(c) for c in CLIPS}
    ver = hashlib.sha1("|".join(f"{k}={v}" for k, v in strs.items()).encode()).hexdigest()[:10]
    lines = [
        "// Generated by tools/anim_clips.py: do not edit (edit the clips there).",
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
        "/** Loads every clip (split over small functions: DiamondFire cannot",
        " * replace a very large code line). */",
        "function loadClips {",
        "    global animStr = {};",
        "    global animData = {};",
        "    global animMeta = {};",
        "    global animMask = {};",
        "    global animVer = animVersion();",
    ]
    groups = [CLIPS[i:i + 2] for i in range(0, len(CLIPS), 2)]
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
    ver = write_tc()
    longest = max(len(clip_string(c)) for c in CLIPS)
    print(f"wrote {OUT_TC.relative_to(ROOT)} ({len(CLIPS)} clips, version {ver}, longest string {longest} chars)")
