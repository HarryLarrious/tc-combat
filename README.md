# tc-combat

A combat game for DiamondFire, written in Terracotta.

## Player model

Each player is drawn as an R6-style rig in their own skin: head, torso, two
arms and two legs. Each part is an item display that holds the player's head,
and the pack's core entity shader (from tc-rally_game) draws each head as the
correct body part. The rig, its joints and the pose format are described at
the top of [tc/rig.tc](tc/rig.tc).

## Animations

Every animation is a clip of key poses in
[tools/anim_clips.py](tools/anim_clips.py): the timing, pose values and easing
for each clip are in one place. Running it writes `tc/anim_data.tc`, which
the game plays. [tc/anim.tc](tc/anim.tc) only picks the clip, finds the time
in it, and crossfades between clips.

- **Movement:** idle (breathing), walk, run, crouch, jump, fall, land, and a
  front flip on a running jump. Walk, run and crouch play over the distance
  walked, so the steps keep pace with the player.
- **Combat stance:** while you hold an item, standing still.
- **Combos:** left click attacks, and clicking again during a swing chains
  the next hit. With an item: slash, backhand, spinning slash. With empty
  hands: right jab, left jab, uppercut.
- **Facing:** the body faces where you walk. The head looks where you look.
- **Emotes:** wave, point, cheer, laugh and dance (`@e NAME`).

To preview clips without the game:

```bash
python3 tools/anim_preview.py walk run
```

This writes `build/anim_preview/<clip>.png`: the clip's frames from the side,
front and three-quarter views, with key frames marked. For walk, run and
crouch it also shows a chart of foot height and foot position, and how far
each foot slides while it is on the ground. After you edit a clip, run
`python3 tools/anim_clips.py` to update the game data.

| Command | Effect |
| --- | --- |
| `@rig` | Turns your player model on or off (it turns on when you join) |
| `@slim` | Toggles slim (3 px) arms |
| `@e NAME` | Plays an emote: wave, point, cheer, laugh, dance |
| `@pose JOINT X Y Z` | Sets a joint's angles in degrees (root, neck, shoulderR, shoulderL, hipR, hipL) or an offset in pixels (rootPos, neckPos, shoulderRPos, shoulderLPos, hipRPos, hipLPos), and stops the animations so the pose holds |
| `@pose reset` | Sets all joints back to rest and starts the animations again |
| `@pack` | Sends the resource pack again |

## Files

| Path | Contents |
| --- | --- |
| [tc/](tc/) | Plot code: the rig (`rig.tc`), its animations (`anim.tc`), commands and events (`commands.tc`), the pack (`pack.tc`) |
| [pack/](pack/) | The resource pack: the skin-part shader and the `combat:body/unit` item model |
| [tools/anim_clips.py](tools/anim_clips.py), [tools/anim_preview.py](tools/anim_preview.py), [tools/rig_fk.py](tools/rig_fk.py) | The animation clips, the contact-sheet previewer, and the rig math they share |
| [tools/build_pack.py](tools/build_pack.py) | Validates the pack, compiles its shaders, builds the zip, and publishes it to the `pack-dist` branch (`--publish --push`) |
