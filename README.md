# tc-combat

A combat game for DiamondFire, written in Terracotta.

## Player model

Each player is drawn as an R6-style rig in their own skin: head, torso, two
arms and two legs. Each part is an item display that holds the player's head,
and the pack's core entity shader (from tc-rally_game) draws each head as the
correct body part. The rig, its joints and the pose format are described at
the top of [tc/rig.tc](tc/rig.tc).

## Animations

[tc/anim.tc](tc/anim.tc) animates the model in the style of a Roblox R6
RPG. Each joint eases toward a target pose every tick.

- **Movement:** breathing idle, bouncy walk, leaning run with pumping arms,
  crouch, jump (knee tucked), fall (arms out), and a landing squash.
- **Combat stance:** while you hold an item, the body turns side-on with the
  weapon arm low and the other arm up to guard.
- **Combos:** left click attacks, and clicking again during a swing chains
  the next hit. With an item: horizontal slash, backhand, overhead slam.
  With an empty hand: right jab, left jab, uppercut.
- **Facing:** the body faces where you walk. The head looks where you look,
  within what a neck allows.
- **Emotes:** wave, point, cheer, laugh and dance. Moving stops them.

| Command | Effect |
| --- | --- |
| `@rig` | Turns your player model on or off (it turns on when you join) |
| `@slim` | Toggles slim (3 px) arms |
| `@e NAME` | Plays an emote: wave, point, cheer, laugh, dance |
| `@pose JOINT X Y Z` | Sets a joint's angles in degrees (root, neck, shoulderR, shoulderL, hipR, hipL) or the root offset in pixels (rootPos), and stops the animations so the pose holds |
| `@pose reset` | Sets all joints back to rest and starts the animations again |
| `@pack` | Sends the resource pack again |

## Files

| Path | Contents |
| --- | --- |
| [tc/](tc/) | Plot code: the rig (`rig.tc`), its animations (`anim.tc`), commands and events (`commands.tc`), the pack (`pack.tc`) |
| [pack/](pack/) | The resource pack: the skin-part shader and the `combat:body/unit` item model |
| [tools/build_pack.py](tools/build_pack.py) | Validates the pack, compiles its shaders, builds the zip, and publishes it to the `pack-dist` branch (`--publish --push`) |
