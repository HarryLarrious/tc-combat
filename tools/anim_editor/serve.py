#!/usr/bin/env python3
"""The animation editor's server.

    python3 tools/anim_editor/serve.py [port]       (default 8770)

Then open http://127.0.0.1:8770/. It listens on 127.0.0.1 only, serves the
editor (this folder), and has a small API:

  GET    /api/clips          every clip (anim/clips/*.json), the joints and
                             the clips the game needs
  PUT    /api/clips/<name>   saves a clip (JSON body), then regenerates
                             tc/anim_data.tc; ?from=<old> renames
  DELETE /api/clips/<name>   deletes a clip (not one the game needs)
  POST   /api/send           compiles the plot code and places it on the
                             plot (the Terracotta skill's tc-send.py), then
                             switches back to play mode
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.parse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import anim_clips  # noqa: E402
import rig_fk  # noqa: E402

# Clips the game's code plays by name (tc/anim.tc): they can be edited but
# not deleted or renamed.
GAME_CLIPS = ["idle", "walk", "run", "crouchIdle", "crouch", "stance", "hold", "jump", "fall", "land",
              "flip", "w1", "w2", "w3", "f1", "f2", "f3"]
SCRIPTS = Path.home() / ".claude/skills/terracotta/scripts"
MAX_BYTES = 1_000_000


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def reply(self, code: int, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        u = urllib.parse.urlparse(self.path)
        return u.path, urllib.parse.parse_qs(u.query)

    def do_GET(self):
        path, _ = self.route()
        if path == "/api/clips":
            clips = []
            for p in sorted(anim_clips.CLIP_DIR.glob("*.json")):
                try:
                    clips.append(anim_clips.normalize(json.loads(p.read_text())))
                except (ValueError, json.JSONDecodeError) as e:
                    clips.append({"name": p.stem, "error": str(e)})
            return self.reply(200, {"clips": clips, "joints": rig_fk.JOINTS, "game": GAME_CLIPS})
        return super().do_GET()

    def do_PUT(self):
        path, q = self.route()
        if not path.startswith("/api/clips/"):
            return self.reply(404, {"error": "not found"})
        name = urllib.parse.unquote(path[len("/api/clips/"):])
        size = int(self.headers.get("Content-Length", 0))
        if size > MAX_BYTES:
            return self.reply(413, {"error": "too large"})
        try:
            doc = json.loads(self.rfile.read(size))
            doc["name"] = name
            doc = anim_clips.normalize(doc)
        except (ValueError, json.JSONDecodeError) as e:
            return self.reply(400, {"error": str(e)})
        old = (q.get("from") or [None])[0]
        if old and old != name:
            if old in GAME_CLIPS:
                return self.reply(400, {"error": f"the game plays '{old}' by name: it cannot be renamed"})
            if (anim_clips.CLIP_DIR / f"{name}.json").exists():
                return self.reply(400, {"error": f"a clip named '{name}' already exists"})
        (anim_clips.CLIP_DIR / f"{name}.json").write_text(anim_clips.format_clip(doc))
        if old and old != name:
            (anim_clips.CLIP_DIR / f"{old}.json").unlink(missing_ok=True)
        try:
            ver = anim_clips.write_tc()
        except Exception as e:  # a bad clip elsewhere
            return self.reply(500, {"error": f"saved, but writing the game data failed: {e}"})
        return self.reply(200, {"ok": True, "version": ver, "clip": doc})

    def do_DELETE(self):
        path, _ = self.route()
        if not path.startswith("/api/clips/"):
            return self.reply(404, {"error": "not found"})
        name = urllib.parse.unquote(path[len("/api/clips/"):])
        if name in GAME_CLIPS:
            return self.reply(400, {"error": f"the game plays '{name}' by name: it cannot be deleted"})
        p = anim_clips.CLIP_DIR / f"{name}.json"
        if not p.exists():
            return self.reply(404, {"error": "no such clip"})
        p.unlink()
        return self.reply(200, {"ok": True, "version": anim_clips.write_tc()})

    def do_POST(self):
        path, _ = self.route()
        if path != "/api/send":
            return self.reply(404, {"error": "not found"})
        send = SCRIPTS / "tc-send.py"
        mode = SCRIPTS / "tc-mode.py"
        if not send.exists():
            return self.reply(500, {"error": f"{send} not found"})
        try:
            r = subprocess.run([sys.executable, str(send), str(ROOT / "tc")], capture_output=True, text=True, timeout=300)
            out = (r.stdout + r.stderr).strip()
            if r.returncode == 0 and mode.exists():
                m = subprocess.run([sys.executable, str(mode), "play"], capture_output=True, text=True, timeout=60)
                out += "\n" + (m.stdout + m.stderr).strip()
        except subprocess.TimeoutExpired:
            return self.reply(500, {"error": "timed out"})
        return self.reply(200 if r.returncode == 0 else 500, {"ok": r.returncode == 0, "output": out[-4000:]})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8770
    handler = partial(Handler, directory=str(HERE))
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"animation editor: http://127.0.0.1:{port}/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
