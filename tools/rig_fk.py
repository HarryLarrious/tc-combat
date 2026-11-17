"""The player rig's math in Python, the same as tc/rig.tc (rigTurn,
rigLimb, rigRender), for the clip generator and the previewer.

Rig frame: +X left, +Y up, +Z forward, in skin pixels; the origin is on
the ground between the feet. A pose is a dict of joint -> (x, y, z).
"""

from __future__ import annotations

import math

JOINTS = [
    "root", "rootPos", "neck", "neckPos",
    "shoulderR", "shoulderRPos", "shoulderL", "shoulderLPos",
    "hipR", "hipRPos", "hipL", "hipLPos",
]
ANGLES = [j for j in JOINTS if not j.endswith("Pos")]

ROOT_Y = 18.0  # torso center above the feet
ARM_W = 4.0


def rest() -> dict:
    return {j: (0.0, 0.0, 0.0) for j in JOINTS}


def turn(B, a):
    """rigTurn: basis (l, u, f) turned by a = (x, y, z) degrees: x about its
    right, then y about its up, then z about its back."""
    l, u, f = B
    x, y, z = a
    if x:
        c, s = math.cos(math.radians(x)), math.sin(math.radians(x))
        u, f = sub(mul(u, c), mul(f, s)), add(mul(f, c), mul(u, s))
    if y:
        c, s = math.cos(math.radians(y)), math.sin(math.radians(y))
        f, l = add(mul(f, c), mul(l, s)), sub(mul(l, c), mul(f, s))
    if z:
        c, s = math.cos(math.radians(z)), math.sin(math.radians(z))
        u, l = add(mul(u, c), mul(l, s)), sub(mul(l, c), mul(u, s))
    return (l, u, f)


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def at(B, p):
    """A point given in basis B (pixels)."""
    return add(add(mul(B[0], p[0]), mul(B[1], p[1])), mul(B[2], p[2]))


def parts(pose: dict, arm_w: float = ARM_W) -> list:
    """The six boxes of a pose: (name, center, basis, size), in the rig
    frame (pixels). Same as rigRender (head look not included)."""
    I = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    root = add((0.0, ROOT_Y, 0.0), pose["rootPos"])
    T = turn(I, pose["root"])
    out = [("torso", root, T, (8, 12, 4))]

    def limb(name, c0, a, c1, size):
        pivot = add(root, at(T, c0))
        B = turn(T, a)
        out.append((name, sub(pivot, at(B, c1)), B, size))

    sx = 4 + arm_w / 2
    limb("head", add((0, 6, 0), pose["neckPos"]), pose["neck"], (0, -4, 0), (8, 8, 8))
    limb("armR", add((-sx, 4, 0), pose["shoulderRPos"]), pose["shoulderR"], (0, 4, 0), (arm_w, 12, 4))
    limb("armL", add((sx, 4, 0), pose["shoulderLPos"]), pose["shoulderL"], (0, 4, 0), (arm_w, 12, 4))
    limb("legR", add((-2, -6, 0), pose["hipRPos"]), pose["hipR"], (0, 6, 0), (4, 12, 4))
    limb("legL", add((2, -6, 0), pose["hipLPos"]), pose["hipL"], (0, 6, 0), (4, 12, 4))
    return out


def corners(center, B, size):
    hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2
    out = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                out.append(add(center, at(B, (sx * hx, sy * hy, sz * hz))))
    return out


def foot_low(pose: dict, leg: str) -> tuple:
    """The lowest corner of a leg ("legR" or "legL"): (x, y, z)."""
    for name, c, B, size in parts(pose):
        if name == leg:
            return min(corners(c, B, size), key=lambda p: p[1])
    raise KeyError(leg)
