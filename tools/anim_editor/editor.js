// R6 animation editor. Edits anim/clips/*.json through serve.py; the game
// plays the same clips (tools/anim_clips.py samples them into
// tc/anim_data.tc on every save).
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import {
  JOINTS, PARTS, PART_OF, JOINT_OF, LABEL_OF, rest, parts, footLow, rawAt, finish, poseAt,
  lookAhead, mirrorPose, isLoop, fullPose, SIDE_SWAP,
} from "./rig.js";

const PX_PER_BLOCK = 1 / 0.05625;
const $ = (id) => document.getElementById(id);
const clone = (o) => JSON.parse(JSON.stringify(o));

// ---------------------------------------------------------------- state

const S = {
  clips: {}, game: [], name: null, origName: null, clip: null, saved: "",
  t: 0, cycles: 0, playing: false, loop: true, speed: 1,
  keyIdx: -1, joint: "shoulderR", onion: false, travel: false, look: true,
  undo: [], redo: [], clipboard: null, editing: false,
};

window.editorState = S; // (for debugging in the console)

function setStatus(msg, cls = "") {
  const el = $("status");
  el.textContent = msg;
  el.className = cls;
  el.title = msg;
}

const isDirty = () => S.clip && JSON.stringify(S.clip) !== S.saved;

// ------------------------------------------------------------ time units

function snapStep() {
  return S.clip.kind === "cycle" ? 1 / 48 : 1 / S.clip.length;
}
const snap = (t) => Math.round(t / snapStep()) * snapStep();

function fmtTime(t) {
  const c = S.clip;
  if (c.kind === "cycle") return `${(t * 100).toFixed(1)}%  ·  ${(t * c.length).toFixed(2)} blocks`;
  return `tick ${(t * c.length).toFixed(1)} / ${c.length}`;
}

function keyAt(t) {
  const eps = snapStep() * 0.49;
  return S.clip.keys.findIndex((k) => Math.abs(k.t - t) < eps);
}

function sortKeys(keep) {
  S.clip.keys.sort((a, b) => a.t - b.t);
  if (keep) S.keyIdx = S.clip.keys.indexOf(keep);
}

// ----------------------------------------------------------- undo / edit

function pushUndo() {
  S.undo.push(JSON.stringify(S.clip));
  if (S.undo.length > 200) S.undo.shift();
  S.redo = [];
}

/** Starts a continuous edit (slider drag, viewport drag): one undo step. */
function beginEdit() {
  if (!S.editing) {
    pushUndo();
    S.editing = true;
  }
}
window.addEventListener("pointerup", () => (S.editing = false));

function undo() {
  if (!S.undo.length) return;
  S.redo.push(JSON.stringify(S.clip));
  S.clip = JSON.parse(S.undo.pop());
  S.keyIdx = Math.min(S.keyIdx, S.clip.keys.length - 1);
  refreshAll();
}

function redo() {
  if (!S.redo.length) return;
  S.undo.push(JSON.stringify(S.clip));
  S.clip = JSON.parse(S.redo.pop());
  refreshAll();
}

/** The key at the playhead, made from the current in-between pose if
 * there is none yet. */
function ensureKey() {
  let i = keyAt(S.t);
  if (i < 0) {
    const { pose, lift } = rawAt(S.clip, S.t);
    const k = { t: snap(S.t), lift: round(lift), ease: "smooth", pose: roundPose(pose) };
    if (!isLoop(S.clip) || k.t < 1) {
      S.clip.keys.push(k);
      sortKeys(k);
      i = S.clip.keys.indexOf(k);
    } else {
      i = 0;
    }
  }
  S.keyIdx = i;
  return S.clip.keys[i];
}

/** Applies fn(key) to the key at the playhead (made if needed). */
function editKey(fn, continuous = false) {
  if (continuous) beginEdit(); else pushUndo();
  const k = ensureKey();
  k.pose = fullPose(k);
  fn(k);
  refreshAll();
}

const round = (v) => Math.round(v * 1000) / 1000;
function roundPose(p) {
  const o = {};
  for (const j of JOINTS) o[j] = p[j].map(round);
  return o;
}

// ------------------------------------------------------------ three.js

const view = $("viewport");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
view.prepend(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x15171c);
const camera = new THREE.PerspectiveCamera(35, 1, 0.5, 2000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 15, 0);
controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xffffff, 0x334055, 1.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.8);
sun.position.set(30, 60, 45);
scene.add(sun);

const grid = new THREE.GridHelper(200, 50, 0x3a4152, 0x2a2f3a);
scene.add(grid);
const ground = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), new THREE.MeshBasicMaterial({ color: 0x1a1d24 }));
ground.rotation.x = -Math.PI / 2;
ground.position.y = -0.05;
scene.add(ground);

const COLORS = { head: 0xf5cd30, torso: 0x0d69ac, armR: 0xd6ac1e, armL: 0xffe270, legR: 0x76962c, legL: 0xacca5c };

function faceTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  g.fillStyle = "#f5cd30";
  g.fillRect(0, 0, 64, 64);
  g.fillStyle = "#222";
  g.fillRect(16, 20, 8, 12);
  g.fillRect(40, 20, 8, 12);
  g.fillRect(18, 44, 28, 5);
  const t = new THREE.CanvasTexture(c);
  t.magFilter = THREE.NearestFilter;
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
const FACE = faceTexture();

function makeRig(ghost) {
  const meshes = {};
  for (const { part } of PARTS) {
    const opts = { color: COLORS[part], transparent: !!ghost, opacity: ghost ? 0.16 : 1, depthWrite: !ghost };
    let mat;
    if (part === "head" && !ghost) {
      const plain = new THREE.MeshLambertMaterial(opts);
      mat = [plain, plain, plain, plain, new THREE.MeshLambertMaterial({ ...opts, color: 0xffffff, map: FACE }), plain];
    } else {
      mat = new THREE.MeshLambertMaterial(opts);
    }
    const m = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), mat);
    m.matrixAutoUpdate = false;
    m.userData.part = part;
    if (!ghost) {
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry), new THREE.LineBasicMaterial({ color: 0x0b0d11 }));
      m.add(edges);
      m.userData.edges = edges;
    }
    scene.add(m);
    meshes[part] = m;
  }
  return meshes;
}
const rig = makeRig(false);
const ghostA = makeRig(true);
const ghostB = makeRig(true);
const pivotMark = new THREE.Mesh(new THREE.SphereGeometry(0.7, 16, 12), new THREE.MeshBasicMaterial({ color: 0x4aa3ff, depthTest: false }));
pivotMark.renderOrder = 10;
scene.add(pivotMark);
const feet = ["legR", "legL"].map(() => {
  const m = new THREE.Mesh(new THREE.CircleGeometry(1.1, 20), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.8 }));
  m.rotation.x = -Math.PI / 2;
  scene.add(m);
  return m;
});

function poseRig(meshes, pose) {
  const ps = parts(pose);
  for (const p of ps) {
    const [l, u, f] = p.basis.map((v) => new THREE.Vector3(...v));
    const m = new THREE.Matrix4().makeBasis(l.multiplyScalar(p.size[0]), u.multiplyScalar(p.size[1]), f.multiplyScalar(p.size[2]));
    m.setPosition(...p.center);
    meshes[p.part].matrix.copy(m);
    meshes[p.part].matrixWorldNeedsUpdate = true;
  }
  return ps;
}

function setVisible(meshes, v) {
  for (const m of Object.values(meshes)) m.visible = v;
}

function displayPose(t) {
  const p = poseAt(S.clip, t);
  return S.look ? lookAhead(p, S.clip.name) : p;
}

function updateScene() {
  if (!S.clip) return;
  const pose = displayPose(S.t);
  const ps = poseRig(rig, pose);
  const selPart = PART_OF[S.joint.replace("Pos", "")];
  for (const p of PARTS) {
    const m = rig[p.part];
    const mats = Array.isArray(m.material) ? m.material : [m.material];
    for (const mat of mats) mat.emissive?.setHex(p.part === selPart ? 0x1d3d66 : 0x000000);
    m.userData.edges.material.color.setHex(p.part === selPart ? 0x4aa3ff : 0x0b0d11);
  }
  const sp = ps.find((p) => p.part === selPart);
  pivotMark.position.set(...sp.pivot);
  // feet: white while touching the ground
  ["legR", "legL"].forEach((leg, i) => {
    const q = footLow(pose, leg);
    feet[i].position.set(q[0], 0.06, q[2]);
    feet[i].material.color.setHex(q[1] < 0.3 ? 0xffffff : 0x555b68);
  });
  // ghosts: the keys before and after the playhead
  const ks = S.clip.keys;
  let prev = null, next = null;
  for (const k of ks) {
    if (k.t < S.t - 1e-6) prev = k;
    if (k.t > S.t + 1e-6 && !next) next = k;
  }
  setVisible(ghostA, S.onion && !!prev);
  setVisible(ghostB, S.onion && !!next);
  if (S.onion && prev) poseRig(ghostA, displayPose(prev.t));
  if (S.onion && next) poseRig(ghostB, displayPose(next.t));
  // the ground moves under a cycle as if walking
  const travel = S.travel && S.clip.kind === "cycle" ? (S.cycles + S.t) * S.clip.length * PX_PER_BLOCK : 0;
  grid.position.z = -(travel % 4);
  $("selName").textContent = LABEL_OF[S.joint.replace("Pos", "")];
}

function resize() {
  const w = view.clientWidth, h = view.clientHeight;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  drawTimeline();
}
window.addEventListener("resize", resize);

function setView(name) {
  const d = 78;
  const dirs = { front: [0, 0.12, 1], side: [-1, 0.12, 0], three: [-0.7, 0.3, 0.75], back: [0, 0.12, -1] };
  const v = new THREE.Vector3(...dirs[name]).normalize().multiplyScalar(d);
  camera.position.copy(controls.target).add(v);
  controls.update();
}
document.querySelectorAll("[data-view]").forEach((b) => (b.onclick = () => setView(b.dataset.view)));

// ------------------------------------------------- viewport: pick and drag

const ray = new THREE.Raycaster();
let drag = null;

function pick(ev) {
  const r = renderer.domElement.getBoundingClientRect();
  const v = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(v, camera);
  const hit = ray.intersectObjects(Object.values(rig), false)[0];
  return hit ? hit.object.userData.part : null;
}

renderer.domElement.addEventListener("pointerdown", (ev) => {
  if (ev.button !== 0 || !S.clip) return;
  const part = pick(ev);
  if (!part) return;
  const joint = JOINT_OF[part];
  const wantPos = ev.altKey;
  S.joint = wantPos ? joint + "Pos" : joint;
  controls.enabled = false;
  drag = { x: ev.clientX, y: ev.clientY, joint, pos: wantPos };
  renderer.domElement.setPointerCapture(ev.pointerId);
  refreshPanels();
});

renderer.domElement.addEventListener("pointermove", (ev) => {
  if (!drag) {
    const part = S.clip && pick(ev);
    renderer.domElement.style.cursor = part ? "grab" : "default";
    $("hint").textContent = part ? `${LABEL_OF[JOINT_OF[part]]}: drag to turn (Shift: twist), Alt+drag to move` : "";
    return;
  }
  const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
  drag.x = ev.clientX;
  drag.y = ev.clientY;
  if (!dx && !dy) return;
  editKey((k) => {
    if (drag.pos) {
      // move in the camera's screen plane, expressed in the torso frame
      const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
      const up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
      const d = right.multiplyScalar(dx * 0.05).add(up.multiplyScalar(-dy * 0.05));
      let B = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
      if (drag.joint !== "root") B = parts(poseAt(S.clip, S.t)).find((p) => p.part === "torso").basis;
      const loc = B.map((a) => a[0] * d.x + a[1] * d.y + a[2] * d.z);
      const j = drag.joint + "Pos";
      k.pose[j] = k.pose[j].map((v, i) => round(v + loc[i]));
    } else {
      const a = k.pose[drag.joint];
      if (ev.shiftKey) a[2] = round(a[2] - dx * 0.5);
      else {
        a[0] = round(a[0] - dy * 0.5);
        a[1] = round(a[1] + dx * 0.5);
      }
    }
  }, true);
});

renderer.domElement.addEventListener("pointerup", () => {
  if (drag) {
    drag = null;
    controls.enabled = true;
  }
});

// ------------------------------------------------------------- timeline

const tl = $("tl");
const tg = tl.getContext("2d");
const TL = { pad: 92, ruler: 22, keys: 24, lane: 15 };
let tlDrag = null;

function tx(t) {
  return TL.pad + t * (tl.clientWidth - TL.pad - 14);
}
function tFromX(x) {
  return Math.min(1, Math.max(0, (x - TL.pad) / (tl.clientWidth - TL.pad - 14)));
}
const laneY = (i) => TL.ruler + TL.keys + i * TL.lane;
const curveTop = () => laneY(PARTS.length) + 6;

function partSet(k, part) {
  const j = JOINT_OF[part];
  return [j, j + "Pos"].some((jj) => (k.pose[jj] || [0, 0, 0]).some((v) => Math.abs(v) > 1e-6));
}

function drawTimeline() {
  const w = tl.clientWidth, h = tl.clientHeight;
  if (tl.width !== w * devicePixelRatio) {
    tl.width = w * devicePixelRatio;
    tl.height = h * devicePixelRatio;
  }
  tg.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  tg.fillStyle = "#1d2027";
  tg.fillRect(0, 0, w, h);
  if (!S.clip) return;
  const c = S.clip;
  tg.font = "11px system-ui";
  // ruler
  tg.fillStyle = "#252932";
  tg.fillRect(0, 0, w, TL.ruler);
  const n = c.kind === "cycle" ? 20 : Math.round(c.length);
  const every = c.kind === "cycle" ? 5 : n > 40 ? 10 : n > 16 ? 5 : n > 8 ? 2 : 1;
  for (let i = 0; i <= n; i++) {
    const x = tx(i / n);
    const major = i % every === 0;
    tg.strokeStyle = major ? "#4a5060" : "#323745";
    tg.beginPath();
    tg.moveTo(x, major ? 8 : 14);
    tg.lineTo(x, h);
    tg.stroke();
    if (major) {
      tg.fillStyle = "#8d93a3";
      tg.fillText(c.kind === "cycle" ? `${i * 5}%` : `${i}`, x + 3, 13);
    }
  }
  // lanes
  tg.fillStyle = "#8d93a3";
  tg.fillText("keys", 10, TL.ruler + 16);
  PARTS.forEach((p, i) => {
    const y = laneY(i);
    if (PART_OF[S.joint.replace("Pos", "")] === p.part) {
      tg.fillStyle = "rgba(74,163,255,.12)";
      tg.fillRect(0, y, w, TL.lane);
    }
    tg.fillStyle = "#8d93a3";
    tg.fillText(p.label, 10, y + 11);
  });
  // keys and lane dots
  c.keys.forEach((k, i) => {
    const x = tx(k.t);
    const y = TL.ruler + TL.keys / 2;
    tg.fillStyle = i === S.keyIdx ? "#f5b335" : "#c9ccd6";
    tg.beginPath();
    tg.moveTo(x, y - 7); tg.lineTo(x + 7, y); tg.lineTo(x, y + 7); tg.lineTo(x - 7, y);
    tg.closePath();
    tg.fill();
    PARTS.forEach((p, li) => {
      if (!partSet(k, p.part)) return;
      tg.fillStyle = i === S.keyIdx ? "#f5b335" : "#6f7686";
      tg.beginPath();
      tg.arc(x, laneY(li) + TL.lane / 2, 3.2, 0, Math.PI * 2);
      tg.fill();
    });
  });
  // the selected joint's curves (x red, y green, z blue)
  const top = curveTop(), bot = h - 6;
  if (bot - top > 20) {
    const N = 120;
    const vals = [];
    for (let i = 0; i <= N; i++) vals.push(rawAt(c, i / N).pose[S.joint]);
    let lo = Math.min(0, ...vals.flat()), hi = Math.max(0, ...vals.flat());
    if (hi - lo < 10) { hi += 5; lo -= 5; }
    const cy = (v) => bot - ((v - lo) / (hi - lo)) * (bot - top);
    tg.strokeStyle = "#3a4152";
    tg.beginPath(); tg.moveTo(TL.pad, cy(0)); tg.lineTo(w - 14, cy(0)); tg.stroke();
    tg.fillStyle = "#8d93a3";
    tg.fillText(S.joint, 10, top + 11);
    tg.fillText(`${Math.round(hi)}`, 10, top + 26);
    tg.fillText(`${Math.round(lo)}`, 10, bot);
    ["#ff6b6b", "#5bd28a", "#4aa3ff"].forEach((col, ci) => {
      tg.strokeStyle = col;
      tg.lineWidth = 1.5;
      tg.beginPath();
      vals.forEach((v, i) => (i ? tg.lineTo(tx(i / N), cy(v[ci])) : tg.moveTo(tx(0), cy(v[ci]))));
      tg.stroke();
      tg.lineWidth = 1;
    });
  }
  // playhead
  const px = tx(S.t);
  tg.strokeStyle = "#f5b335";
  tg.beginPath(); tg.moveTo(px, 0); tg.lineTo(px, h); tg.stroke();
}

function keyNear(x, y) {
  if (y < TL.ruler || y > laneY(PARTS.length)) return -1;
  let best = -1, bd = 9;
  S.clip.keys.forEach((k, i) => {
    const d = Math.abs(tx(k.t) - x);
    if (d < bd) { bd = d; best = i; }
  });
  return best;
}

tl.addEventListener("pointerdown", (ev) => {
  if (!S.clip) return;
  const r = tl.getBoundingClientRect();
  const x = ev.clientX - r.left, y = ev.clientY - r.top;
  tl.setPointerCapture(ev.pointerId);
  const i = keyNear(x, y);
  if (y >= laneY(0) && y < laneY(PARTS.length)) {
    const li = Math.floor((y - laneY(0)) / TL.lane);
    S.joint = PARTS[li].joint;
  }
  if (i >= 0) {
    S.keyIdx = i;
    S.t = S.clip.keys[i].t;
    S.playing = false;
    tlDrag = { key: S.clip.keys[i], moved: false };
  } else {
    S.keyIdx = -1;
    S.t = snap(tFromX(x));
    tlDrag = { scrub: true };
  }
  refreshAll();
});

tl.addEventListener("pointermove", (ev) => {
  if (!tlDrag) return;
  const r = tl.getBoundingClientRect();
  const t = ev.shiftKey ? tFromX(ev.clientX - r.left) : snap(tFromX(ev.clientX - r.left));
  if (tlDrag.scrub) {
    S.t = t;
  } else {
    const k = tlDrag.key;
    let nt = isLoop(S.clip) ? Math.min(t, 1 - snapStep()) : t;
    if (S.clip.keys.some((o) => o !== k && Math.abs(o.t - nt) < 1e-6)) return;
    if (!tlDrag.moved) { pushUndo(); tlDrag.moved = true; }
    k.t = round(nt);
    sortKeys(k);
    S.t = k.t;
  }
  refreshAll();
});

tl.addEventListener("pointerup", () => (tlDrag = null));
tl.addEventListener("dblclick", (ev) => {
  const r = tl.getBoundingClientRect();
  if (ev.clientY - r.top > laneY(0)) return;
  S.t = snap(tFromX(ev.clientX - r.left));
  addKey();
});

// -------------------------------------------------------------- panels

const AXES = ["x", "y", "z"];

function buildJointPanel() {
  const sel = $("jSel");
  sel.innerHTML = "";
  for (const p of PARTS) sel.add(new Option(p.label, p.joint));
  sel.onchange = () => { S.joint = sel.value; refreshAll(); };
  for (const [boxId, pos] of [["jAng", false], ["jPos", true]]) {
    const box = $(boxId);
    box.innerHTML = "";
    AXES.forEach((ax, ci) => {
      const row = document.createElement("div");
      row.className = "axis";
      const range = document.createElement("input");
      range.type = "range";
      range.min = pos ? -10 : -180;
      range.max = pos ? 10 : 180;
      range.step = pos ? 0.1 : 1;
      const numIn = document.createElement("input");
      numIn.type = "number";
      numIn.step = pos ? 0.1 : 1;
      row.innerHTML = `<b class="${ax}">${ax.toUpperCase()}</b>`;
      row.append(range, numIn);
      box.append(row);
      const apply = (v, cont) => {
        const val = parseFloat(v);
        if (!isFinite(val)) return;
        const j = PART_OF[S.joint.replace("Pos", "")] && (pos ? S.joint.replace("Pos", "") + "Pos" : S.joint.replace("Pos", ""));
        editKey((k) => { k.pose[j][ci] = round(val); }, cont);
      };
      range.addEventListener("pointerdown", beginEdit);
      range.addEventListener("input", () => apply(range.value, true));
      numIn.addEventListener("change", () => apply(numIn.value, false));
      row.dataset.joint = pos ? "pos" : "ang";
      row.dataset.axis = ci;
    });
  }
}

const HELP = {
  root: "The whole body. X + leans back, Y + turns left, Z + tips left. Move: shifts the body (Y up).",
  neck: "X + tips the head up, Y + turns it left, Z + tilts it left. In the game the head also looks where the player looks.",
  shoulderR: "X + swings the arm forward and up (90 points ahead, 180 straight up). Y + turns it toward the body's left. Z + raises it out to the side.",
  shoulderL: "X + swings the arm forward and up (90 points ahead, 180 straight up). Y + turns it toward the body's left. Z − raises it out to the side.",
  hipR: "X + swings the leg forward. Z + swings it out to the side. Move Y + lifts the leg: R6 has no knees, so a lifted leg reads as a bent knee.",
  hipL: "X + swings the leg forward. Z − swings it out to the side. Move Y + lifts the leg: R6 has no knees, so a lifted leg reads as a bent knee.",
};

function refreshPanels() {
  const c = S.clip;
  if (!c) return;
  $("clipTitle").textContent = c.name;
  $("dirty").hidden = !isDirty();
  $("cName").value = c.name;
  $("cKind").value = c.kind;
  $("cLength").value = c.length;
  $("cLength").step = c.kind === "cycle" ? 0.1 : 1;
  $("cLenLabel").textContent = c.kind === "cycle" ? "Blocks" : "Ticks";
  $("cLength").title = c.kind === "cycle" ? "Blocks walked per full cycle (two steps)" : "Length in ticks (20 a second)";
  $("cFade").value = c.fade;
  $("cInterp").value = c.interp;
  $("cPlanted").checked = c.planted;
  $("cCounter").checked = c.counter;
  $("cEmote").checked = c.emote;
  if (document.activeElement !== $("cNotes")) $("cNotes").value = c.notes || "";
  $("delClip").disabled = S.game.includes(S.origName);
  $("delClip").title = S.game.includes(S.origName) ? "The game plays this clip by name: it cannot be deleted" : "Delete this clip";
  $("cName").disabled = S.game.includes(S.origName);
  // key
  const ki = keyAt(S.t);
  const k = ki >= 0 ? c.keys[ki] : null;
  $("keyInfo").textContent = k ? `${ki + 1} of ${c.keys.length}` : `none here (${c.keys.length} keys): editing adds one`;
  for (const id of ["kTime", "kEase", "kLift"]) $(id).disabled = !k;
  $("kTime").value = k ? (c.kind === "cycle" ? round(k.t * 100) : round(k.t * c.length)) : "";
  $("kTimeUnit").textContent = c.kind === "cycle" ? "% of the cycle" : "ticks";
  $("kEase").value = k ? k.ease : "smooth";
  $("kEase").disabled = !k || c.interp === "spline";
  $("kEase").title = c.interp === "spline" ? "Spline clips move smoothly through every key" : "How the motion arrives at this key";
  $("kLift").value = k ? k.lift : "";
  $("delKey").disabled = !k || c.keys.length <= 1;
  // joint
  const base = S.joint.replace("Pos", "");
  $("jSel").value = base;
  $("jTitle").textContent = "Part";
  const raw = k ? fullPose(k) : rawAt(c, S.t).pose;
  for (const [boxId, j] of [["jAng", base], ["jPos", base + "Pos"]]) {
    $(boxId).querySelectorAll(".axis").forEach((row) => {
      const [range, numIn] = row.querySelectorAll("input");
      const v = raw[j][+row.dataset.axis];
      if (document.activeElement !== numIn) numIn.value = round(v);
      range.value = v;
      row.style.opacity = k ? 1 : 0.6;
    });
  }
  $("jMirror").disabled = !SIDE_SWAP[base];
  $("jHelp").textContent = HELP[base];
  $("time").textContent = fmtTime(S.t);
  $("undo").disabled = !S.undo.length;
  $("redo").disabled = !S.redo.length;
  renderClipList();
}

function refreshAll() {
  refreshPanels();
  updateScene();
  drawTimeline();
}

function renderClipList() {
  const box = $("clipList");
  const names = Object.keys(S.clips).sort();
  const groups = [
    ["Movement and combat (the game plays these)", names.filter((n) => S.game.includes(n))],
    ["Emotes (@e name)", names.filter((n) => !S.game.includes(n) && S.clips[n].emote)],
    ["Other", names.filter((n) => !S.game.includes(n) && !S.clips[n].emote)],
  ];
  box.innerHTML = "";
  for (const [title, list] of groups) {
    if (!list.length) continue;
    const g = document.createElement("div");
    g.className = "grp";
    g.textContent = title;
    box.append(g);
    for (const n of list) {
      const a = document.createElement("a");
      a.className = n === S.origName ? "cur" : "";
      const doc = S.clips[n];
      a.innerHTML = `<span>${n}</span><small>${doc.kind}</small>`;
      a.onclick = () => openClip(n);
      box.append(a);
    }
  }
}

// ---------------------------------------------------------- clip actions

function openClip(name, force = false) {
  if (!force && isDirty() && name !== S.origName && !confirm(`Discard the unsaved changes to ${S.clip.name}?`)) return;
  S.origName = name;
  S.isNew = false;
  S.clip = clone(S.clips[name]);
  S.saved = JSON.stringify(S.clip);
  S.t = 0;
  S.cycles = 0;
  S.keyIdx = 0;
  S.undo = [];
  S.redo = [];
  history.replaceState(null, "", `#${name}`);
  refreshAll();
}

function addKey() {
  if (keyAt(S.t) >= 0) return;
  if (isLoop(S.clip) && snap(S.t) >= 1) S.t = 0;
  pushUndo();
  ensureKey();
  refreshAll();
}

function deleteKey() {
  const i = keyAt(S.t);
  if (i < 0 || S.clip.keys.length <= 1) return;
  pushUndo();
  S.clip.keys.splice(i, 1);
  S.keyIdx = -1;
  refreshAll();
}

function stepKey(dir) {
  const ks = S.clip.keys;
  const cand = dir > 0 ? ks.find((k) => k.t > S.t + 1e-6) : [...ks].reverse().find((k) => k.t < S.t - 1e-6);
  if (cand) S.t = cand.t;
  else if (isLoop(S.clip)) S.t = dir > 0 ? ks[0].t : ks[ks.length - 1].t;
  refreshAll();
}

function step(dir) {
  S.t = snap(S.t + dir * snapStep());
  if (S.t < 0) S.t = isLoop(S.clip) ? 1 - snapStep() : 0;
  if (S.t > 1 - (isLoop(S.clip) ? snapStep() / 2 : -1e-9)) S.t = isLoop(S.clip) ? 0 : 1;
  refreshAll();
}

async function save() {
  const c = S.clip;
  const renamed = S.origName !== c.name;
  const from = renamed && !S.isNew ? `?from=${encodeURIComponent(S.origName)}` : "";
  setStatus("Saving…");
  try {
    const r = await fetch(`/api/clips/${encodeURIComponent(c.name)}${from}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(c),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    if (renamed) delete S.clips[S.origName];
    S.isNew = false;
    S.clips[c.name] = j.clip;
    S.clip = clone(j.clip);
    S.origName = c.name;
    S.saved = JSON.stringify(S.clip);
    history.replaceState(null, "", `#${c.name}`);
    setStatus(`Saved ${c.name}. Game data updated: press "Send to game" to put it on the plot.`, "good");
    refreshAll();
  } catch (e) {
    setStatus(`Not saved: ${e.message}`, "bad");
  }
}

async function sendToGame() {
  if (isDirty()) await save();
  $("send").disabled = true;
  setStatus("Compiling and placing the code on the plot… (accept in Minecraft chat if it asks)");
  try {
    const r = await fetch("/api/send", { method: "POST" });
    const j = await r.json();
    const last = (j.output || j.error || "").trim().split("\n").filter(Boolean).slice(-2).join(" · ");
    setStatus(j.ok ? `On the plot. ${last}` : `Send failed: ${last}`, j.ok ? "good" : "bad");
  } catch (e) {
    setStatus(`Send failed: ${e.message}`, "bad");
  }
  $("send").disabled = false;
}

function newClip(copyOf) {
  let name = prompt(copyOf ? "Name for the copy:" : "Name for the new clip (letters, digits, - and _):", copyOf ? `${copyOf.name}_copy` : "");
  if (!name) return;
  name = name.trim();
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(name)) return setStatus("Clip names use letters, digits, - and _", "bad");
  if (S.clips[name]) return setStatus(`A clip named ${name} already exists`, "bad");
  const doc = copyOf ? { ...clone(copyOf), name } : {
    name, kind: "once", length: 20, interp: "ease", planted: true, counter: true, fade: 3, samples: 0,
    emote: true, mask: [], notes: "",
    keys: [{ t: 0, lift: 0, ease: "smooth", pose: {} }, { t: 0.5, lift: 0, ease: "smooth", pose: {} }, { t: 1, lift: 0, ease: "smooth", pose: {} }],
  };
  if (copyOf && S.game.includes(copyOf.name)) doc.emote = true;
  if (isDirty() && !confirm(`Discard the unsaved changes to ${S.clip.name}?`)) return;
  S.clips[name] = doc;
  openClip(name, true);
  S.isNew = true; // not on disk yet: Save creates it
  S.saved = "";
  setStatus(`New clip ${name}: pose it, then Save.`);
  refreshPanels();
}

async function deleteClip() {
  if (!confirm(`Delete the clip ${S.origName}? This removes anim/clips/${S.origName}.json.`)) return;
  if (S.isNew) {
    delete S.clips[S.origName];
    return openClip(Object.keys(S.clips).sort()[0], true);
  }
  const r = await fetch(`/api/clips/${encodeURIComponent(S.origName)}`, { method: "DELETE" });
  const j = await r.json();
  if (!r.ok && r.status !== 404) return setStatus(j.error, "bad");
  delete S.clips[S.origName];
  openClip(Object.keys(S.clips).sort()[0], true);
  setStatus("Clip deleted. Game data updated.", "good");
}

// ---------------------------------------------------------------- wiring

function clipField(id, key, parse = (v) => v, prop = "value") {
  $(id).addEventListener("change", () => {
    pushUndo();
    S.clip[key] = parse($(id)[prop]);
    if (key === "kind" && S.clip.kind !== "once") {
      // a looping clip's last key at t = 1 is its first key again
      S.clip.keys = S.clip.keys.filter((k) => k.t < 1 - 1e-6);
      if (!S.clip.keys.length) S.clip.keys = [{ t: 0, lift: 0, ease: "smooth", pose: {} }];
    }
    refreshAll();
  });
}
clipField("cName", "name", (v) => v.trim());
clipField("cKind", "kind");
clipField("cLength", "length", (v) => Math.max(0.1, parseFloat(v) || 1));
clipField("cFade", "fade", (v) => Math.max(1, parseInt(v) || 1));
clipField("cInterp", "interp");
clipField("cPlanted", "planted", (v) => v, "checked");
clipField("cCounter", "counter", (v) => v, "checked");
clipField("cEmote", "emote", (v) => v, "checked");
$("cNotes").addEventListener("change", () => { pushUndo(); S.clip.notes = $("cNotes").value; refreshPanels(); });

$("kTime").addEventListener("change", () => {
  const i = keyAt(S.t);
  if (i < 0) return;
  const k = S.clip.keys[i];
  const v = parseFloat($("kTime").value);
  let t = S.clip.kind === "cycle" ? v / 100 : v / S.clip.length;
  t = Math.min(isLoop(S.clip) ? 1 - 1e-3 : 1, Math.max(0, t));
  if (S.clip.keys.some((o) => o !== k && Math.abs(o.t - t) < 1e-6)) return setStatus("Another key is already there", "bad");
  pushUndo();
  k.t = round(t);
  sortKeys(k);
  S.t = k.t;
  refreshAll();
});
$("kEase").addEventListener("change", () => editKey((k) => (k.ease = $("kEase").value)));
$("kLift").addEventListener("change", () => editKey((k) => (k.lift = round(parseFloat($("kLift").value) || 0))));

$("jReset").onclick = () => editKey((k) => {
  const b = S.joint.replace("Pos", "");
  k.pose[b] = [0, 0, 0];
  k.pose[b + "Pos"] = [0, 0, 0];
});
$("jMirror").onclick = () => editKey((k) => {
  const b = S.joint.replace("Pos", "");
  const m = mirrorPose({ [b]: k.pose[b], [b + "Pos"]: k.pose[b + "Pos"] });
  Object.assign(k.pose, m);
});

$("play").onclick = () => togglePlay();
$("loop").onclick = () => { S.loop = !S.loop; $("loop").classList.toggle("on", S.loop); };
$("speed").onchange = () => (S.speed = parseFloat($("speed").value));
$("addKey").onclick = addKey;
$("delKey").onclick = deleteKey;
$("copyPose").onclick = copyPose;
$("pastePose").onclick = pastePose;
$("mirror").onclick = () => editKey((k) => (k.pose = { ...rest(), ...mirrorPose(k.pose) }));
$("save").onclick = save;
$("send").onclick = sendToGame;
$("undo").onclick = undo;
$("redo").onclick = redo;
$("newClip").onclick = () => newClip(null);
$("dupClip").onclick = () => newClip(S.clip);
$("delClip").onclick = deleteClip;
$("onion").onclick = () => { S.onion = !S.onion; $("onion").classList.toggle("on", S.onion); updateScene(); };
$("travel").onclick = () => { S.travel = !S.travel; $("travel").classList.toggle("on", S.travel); updateScene(); };
$("lookAhead").onclick = () => { S.look = !S.look; $("lookAhead").classList.toggle("on", S.look); updateScene(); };

function copyPose() {
  const { pose, lift } = rawAt(S.clip, S.t);
  S.clipboard = { pose: roundPose(pose), lift };
  setStatus("Pose copied.");
}
function pastePose() {
  if (!S.clipboard) return setStatus("Copy a pose first.", "bad");
  editKey((k) => { k.pose = clone(S.clipboard.pose); k.lift = S.clipboard.lift; });
}

function togglePlay() {
  S.playing = !S.playing;
  if (S.playing && !isLoop(S.clip) && S.t >= 1) S.t = 0;
  $("play").textContent = S.playing ? "❚❚ Pause" : "▶ Play";
}

window.addEventListener("keydown", (ev) => {
  const tag = document.activeElement?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
    if (ev.key === "Escape") document.activeElement.blur();
    return;
  }
  const ctrl = ev.ctrlKey || ev.metaKey;
  if (ctrl && ev.key.toLowerCase() === "s") { ev.preventDefault(); save(); return; }
  if (ctrl && ev.key.toLowerCase() === "z") { ev.preventDefault(); ev.shiftKey ? redo() : undo(); return; }
  if (ctrl && ev.key.toLowerCase() === "y") { ev.preventDefault(); redo(); return; }
  if (ctrl && ev.key.toLowerCase() === "c") { copyPose(); return; }
  if (ctrl && ev.key.toLowerCase() === "v") { pastePose(); return; }
  if (!S.clip || ctrl) return;
  if (ev.key === " ") { ev.preventDefault(); togglePlay(); }
  else if (ev.key === "ArrowRight") { ev.preventDefault(); ev.shiftKey ? stepKey(1) : step(1); }
  else if (ev.key === "ArrowLeft") { ev.preventDefault(); ev.shiftKey ? stepKey(-1) : step(-1); }
  else if (ev.key === "k" || ev.key === "K") addKey();
  else if (ev.key === "Delete" || ev.key === "Backspace") deleteKey();
  else if (ev.key === "m" || ev.key === "M") $("mirror").click();
  else if (ev.key >= "1" && ev.key <= "6") { S.joint = PARTS[+ev.key - 1].joint; refreshAll(); }
});

window.addEventListener("beforeunload", (ev) => {
  if (isDirty()) { ev.preventDefault(); ev.returnValue = ""; }
});

// ------------------------------------------------------------------ loop

let last = performance.now();
function frame(now) {
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  if (S.playing && S.clip) {
    const c = S.clip;
    // seconds per pass: ticks at 20 a second; a cycle at walking speed
    const dur = c.kind === "cycle" ? c.length / 4.3 : c.length / 20;
    S.t += (dt * S.speed) / dur;
    if (S.t >= 1) {
      if (isLoop(c)) { S.t -= 1; S.cycles++; }
      else if (S.loop) S.t = 0;
      else { S.t = 1; togglePlay(); }
    }
    updateScene();
    drawTimeline();
    $("time").textContent = fmtTime(S.t);
  }
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}

// ------------------------------------------------------------------ boot

async function boot() {
  buildJointPanel();
  setView("three");
  resize();
  try {
    const r = await fetch("/api/clips");
    const j = await r.json();
    S.game = j.game;
    for (const c of j.clips) if (!c.error) S.clips[c.name] = c;
    const bad = j.clips.filter((c) => c.error);
    if (bad.length) setStatus(`Could not read: ${bad.map((c) => `${c.name} (${c.error})`).join(", ")}`, "bad");
  } catch (e) {
    setStatus("Cannot reach the editor server: run python3 tools/anim_editor/serve.py", "bad");
    return;
  }
  const want = decodeURIComponent(location.hash.slice(1));
  openClip(S.clips[want] ? want : "idle" in S.clips ? "idle" : Object.keys(S.clips)[0]);
  requestAnimationFrame(frame);
}
boot();
