# tc-combat

A combat game for DiamondFire, written in Terracotta.

## Player model

Each player is drawn as an R6-style rig in their own skin: head, torso, two
arms and two legs. Each part is an item display that holds the player's head,
and the pack's core entity shader (from tc-rally_game) draws each head as the
correct body part. The rig, its joints and the pose format are described at
the top of [tc/rig.tc](tc/rig.tc).

## Animations

Every animation is a clip: a few key poses on a timeline, saved as
`anim/clips/<name>.json`. `tools/anim_clips.py` samples the clips into
`tc/anim_data.tc`, which the game plays. [tc/anim.tc](tc/anim.tc) only picks
the clip, finds the time in it, and crossfades between clips.

### The animation editor

```bash
python3 tools/anim_editor/serve.py
```

Then open http://127.0.0.1:8770/. Use it to:

- **Pose:** click a body part, then drag it to turn it (up/down: X,
  sideways: Y, with Shift: Z). Drag with Alt to move it off the body. You
  can also use the sliders and number fields in the panel on the right.
  Editing between two keys adds a key at the playhead.
- **Time:** the timeline shows the keys (drag them to retime), a lane per
  body part with a dot where a key sets that part, and the curves of the
  selected part (X red, Y green, Z blue). Click or drag the ruler to scrub.
  Double-click to add a key.
- **Check:** play, loop, slow down, show the keys before and after as
  ghosts, move the ground under walk cycles (planted feet should stay on the
  grid), and use the side, front, three-quarter and back views. White
  circles mark feet that touch the ground.
- **Save:** Ctrl+S writes the clip and updates the game data. "Send to game"
  compiles the plot code and places it on the plot.

Keys: Space play, ← → step (Shift: to the next key), K add key, Delete
delete key, Ctrl+C / Ctrl+V copy and paste a pose, M mirror the pose, 1–6
pick a body part, Ctrl+Z / Ctrl+Shift+Z undo and redo.

The game plays the movement and combat clips by name, so you can edit them
but not rename or delete them. A clip marked **Emote** can be played in game
with `@e NAME`. Make a new clip with "New", tick Emote, save, and send.

### What plays when

- **Movement:** idle, walk (slow movement), run (normal speed and
  sprinting, as in Roblox), crouch, crouchIdle, jump, fall, land, and flip
  (a sprinting jump). Walk, run and crouch play over the distance walked, so
  the steps keep pace with the player.
- **Combat:** stance (standing with an item), hold (the weapon arm while
  walking with an item), and the combos: w1, w2, w3 with an item, and f1,
  f2, f3 with empty hands. Clicking during a swing chains the next hit.
- **Facing:** the body faces where you walk. The head looks where you look.

### Contact sheets

```bash
python3 tools/anim_preview.py walk run
```

This writes `build/anim_preview/<clip>.png`: the clip's frames from the side,
front and three-quarter views, with key frames marked. For cycles it also
charts foot height and position, and how far each foot slides while on the
ground.

| Command | Effect |
| --- | --- |
| `@rig` | Turns your player model on or off (it turns on when you join) |
| `@slim` | Toggles slim (3 px) arms |
| `@e NAME` | Plays an emote: wave, point, cheer, laugh, dance |
| `@pose JOINT X Y Z` | Sets a joint's angles in degrees (root, neck, shoulderR, shoulderL, hipR, hipL) or an offset in pixels (rootPos, neckPos, shoulderRPos, shoulderLPos, hipRPos, hipLPos), and stops the animations so the pose holds |
| `@pose reset` | Sets all joints back to rest and starts the animations again |
| `@animdebug` | Shows the playing clip and the inputs that chose it (speed, sprint, sneak, air, item) in the action bar |
| `@pack` | Sends the resource pack again |

## Files

| Path | Contents |
| --- | --- |
| [tc/](tc/) | Plot code: the rig (`rig.tc`), its animations (`anim.tc`), commands and events (`commands.tc`), the pack (`pack.tc`) |
| [pack/](pack/) | The resource pack: the skin-part shader and the `combat:body/unit` item model |
| [anim/clips/](anim/clips/) | The animation clips (JSON), one per file |
| [tools/anim_editor/](tools/anim_editor/) | The animation editor (`serve.py`, then open http://127.0.0.1:8770/) |
| [tools/anim_clips.py](tools/anim_clips.py), [tools/anim_preview.py](tools/anim_preview.py), [tools/rig_fk.py](tools/rig_fk.py) | Clip sampling into `tc/anim_data.tc`, the contact-sheet previewer, and the rig math they share |
| [tools/build_pack.py](tools/build_pack.py) | Validates the pack, compiles its shaders, builds the zip, and publishes it to the `pack-dist` branch (`--publish --push`) |
