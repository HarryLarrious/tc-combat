// The rig math and clip sampling, the same as tools/rig_fk.py and
// tools/anim_clips.py (keep them in step). Rig frame: +X left, +Y up, +Z
// forward, skin pixels, origin on the ground between the feet.

export const JOINTS = [
  "root", "rootPos", "neck", "neckPos",
  "shoulderR", "shoulderRPos", "shoulderL", "shoulderLPos",
  "hipR", "hipRPos", "hipL", "hipLPos",
];

// Each body part and the joint that moves it.
export const PARTS = [
  { part: "torso", joint: "root", label: "Torso" },
  { part: "head", joint: "neck", label: "Head" },
  { part: "armR", joint: "shoulderR", label: "Right Arm" },
  { part: "armL", joint: "shoulderL", label: "Left Arm" },
  { part: "legR", joint: "hipR", label: "Right Leg" },
  { part: "legL", joint: "hipL", label: "Left Leg" },
];
export const PART_OF = Object.fromEntries(PARTS.map((p) => [p.joint, p.part]));
export const JOINT_OF = Object.fromEntries(PARTS.map((p) => [p.part, p.joint]));
export const LABEL_OF = Object.fromEntries(PARTS.map((p) => [p.joint, p.label]));

const ROOT_Y = 18;
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
const rad = (d) => (d * Math.PI) / 180;

export function rest() {
  return Object.fromEntries(JOINTS.map((j) => [j, [0, 0, 0]]));
}

/** rigTurn: basis [l, u, f] turned by a = [x, y, z] degrees. */
export function turn(B, a) {
  let [l, u, f] = B;
  const [x, y, z] = a;
  if (x) {
    const c = Math.cos(rad(x)), s = Math.sin(rad(x));
    [u, f] = [sub(mul(u, c), mul(f, s)), add(mul(f, c), mul(u, s))];
  }
  if (y) {
    const c = Math.cos(rad(y)), s = Math.sin(rad(y));
    [f, l] = [add(mul(f, c), mul(l, s)), sub(mul(l, c), mul(f, s))];
  }
  if (z) {
    const c = Math.cos(rad(z)), s = Math.sin(rad(z));
    [u, l] = [add(mul(u, c), mul(l, s)), sub(mul(l, c), mul(u, s))];
  }
  return [l, u, f];
}

const at = (B, p) => add(add(mul(B[0], p[0]), mul(B[1], p[1])), mul(B[2], p[2]));

/** The six boxes of a pose: {part, center, basis, size, pivot}. */
export function parts(pose, armW = 4) {
  const I = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  const root = add([0, ROOT_Y, 0], pose.rootPos);
  const T = turn(I, pose.root);
  const out = [{ part: "torso", center: root, basis: T, size: [8, 12, 4], pivot: root }];
  const limb = (part, c0, a, c1, size) => {
    const pivot = add(root, at(T, c0));
    const B = turn(T, a);
    out.push({ part, center: sub(pivot, at(B, c1)), basis: B, size, pivot });
  };
  const sx = 4 + armW / 2;
  limb("head", add([0, 6, 0], pose.neckPos), pose.neck, [0, -4, 0], [8, 8, 8]);
  limb("armR", add([-sx, 4, 0], pose.shoulderRPos), pose.shoulderR, [0, 4, 0], [armW, 12, 4]);
  limb("armL", add([sx, 4, 0], pose.shoulderLPos), pose.shoulderL, [0, 4, 0], [armW, 12, 4]);
  limb("legR", add([-2, -6, 0], pose.hipRPos), pose.hipR, [0, 6, 0], [4, 12, 4]);
  limb("legL", add([2, -6, 0], pose.hipLPos), pose.hipL, [0, 6, 0], [4, 12, 4]);
  return out;
}

function corners(p) {
  const out = [];
  for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1])
    out.push(add(p.center, at(p.basis, [sx * p.size[0] / 2, sy * p.size[1] / 2, sz * p.size[2] / 2])));
  return out;
}

/** The lowest corner of a leg ("legR" / "legL"). */
export function footLow(pose, leg) {
  const p = parts(pose).find((q) => q.part === leg);
  return corners(p).reduce((a, b) => (b[1] < a[1] ? b : a));
}

// ------------------------------------------------------------- sampling

function easeFn(name, u) {
  if (name === "linear") return u;
  if (name === "in") return u * u;
  if (name === "out") return 1 - (1 - u) * (1 - u);
  return u * u * (3 - 2 * u);
}

function catmull(p0, p1, p2, p3, u) {
  return 0.5 * (2 * p1 + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u + (-p0 + 3 * p1 - 3 * p2 + p3) * u * u * u);
}

export function fullPose(k) {
  const p = rest();
  for (const [j, v] of Object.entries(k.pose || {})) p[j] = [...v];
  return p;
}

export const isLoop = (clip) => clip.kind === "cycle" || clip.kind === "loop";

/** The interpolated {pose, lift} at t (0..1), before post-processing. */
export function rawAt(clip, t) {
  const keys = [...clip.keys].sort((a, b) => a.t - b.t).map((k) => ({ ...k, full: fullPose(k) }));
  let ext = keys;
  if (isLoop(clip)) {
    t = ((t % 1) + 1) % 1;
    const n = keys.length;
    const sh = (i, dt) => { const k = keys[((i % n) + n) % n]; return { ...k, t: k.t + dt }; };
    ext = [sh(n - 2, -1), sh(n - 1, -1), ...keys, sh(0, 1), sh(1, 1)];
  } else {
    if (t <= keys[0].t) return { pose: keys[0].full, lift: keys[0].lift };
    const last = keys[keys.length - 1];
    if (t >= last.t) return { pose: last.full, lift: last.lift };
  }
  let i = 0;
  for (let k = 0; k < ext.length - 1; k++) if (ext[k].t <= t) i = k;
  const a = ext[i], b = ext[i + 1];
  const u = b.t === a.t ? 0 : (t - a.t) / (b.t - a.t);
  const p0 = i > 0 ? ext[i - 1] : a;
  const p3 = i + 2 < ext.length ? ext[i + 2] : b;
  const mix = (va, vb, v0, v3) => clip.interp === "spline" ? catmull(v0, va, vb, v3, u) : va + (vb - va) * easeFn(b.ease, u);
  const pose = {};
  for (const j of JOINTS) pose[j] = [0, 1, 2].map((c) => mix(a.full[j][c], b.full[j][c], p0.full[j][c], p3.full[j][c]));
  return { pose, lift: mix(a.lift, b.lift, p0.lift, p3.lift) };
}

/** Post-processing (counter, planted) of a raw pose, as the game gets it. */
export function finish(clip, pose, lift) {
  const p = Object.fromEntries(Object.entries(pose).map(([k, v]) => [k, [...v]]));
  if (clip.counter) {
    for (const h of ["hipR", "hipL"]) p[h] = sub(p[h], p.root);
  }
  const [x, y, z] = p.rootPos;
  if (clip.planted) {
    const low = Math.min(footLow(p, "legR")[1], footLow(p, "legL")[1]);
    p.rootPos = [x, y - low + lift, z];
  } else {
    p.rootPos = [x, y + lift, z];
  }
  return p;
}

export function poseAt(clip, t) {
  const { pose, lift } = rawAt(clip, t);
  return finish(clip, pose, lift);
}

/** The head looking straight ahead (the game turns the neck back against
 * the torso so the head keeps looking where the player looks). */
export function lookAhead(pose, clipName) {
  if (clipName === "w3") return pose;
  const wrap = (a) => ((a + 180) % 360 + 360) % 360 - 180;
  const p = { ...pose };
  const r = pose.root;
  const nx = Math.max(-50, Math.min(60, -wrap(r[0])));
  const ny = Math.max(-70, Math.min(70, -wrap(r[1])));
  p.neck = [pose.neck[0] + nx, pose.neck[1] + ny, pose.neck[2]];
  return p;
}

// --------------------------------------------------------------- mirror

const SWAP = { shoulderR: "shoulderL", shoulderL: "shoulderR", hipR: "hipL", hipL: "hipR",
  shoulderRPos: "shoulderLPos", shoulderLPos: "shoulderRPos", hipRPos: "hipLPos", hipLPos: "hipRPos" };

/** A pose (joint -> [x, y, z]) mirrored left to right. */
export function mirrorPose(pose) {
  const out = {};
  for (const [j, [x, y, z]] of Object.entries(pose)) {
    const d = SWAP[j] || j;
    out[d] = j.endsWith("Pos") ? [-x, y, z] : [x, -y, -z];
  }
  return out;
}

export const SIDE_SWAP = SWAP;
