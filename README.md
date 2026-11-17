# tc-combat

A combat game for DiamondFire, written in Terracotta.

## Player model

Each player is drawn as an R6-style rig in their own skin: head, torso, two
arms and two legs. Each part is an item display that holds the player's head,
and the pack's core entity shader (from tc-rally_game) draws each head as the
correct body part. The rig, its joints and the pose format are described at
the top of [tc/rig.tc](tc/rig.tc).

| Command | Effect |
| --- | --- |
| `@rig` | Turns your player model on or off (it turns on when you join) |
| `@slim` | Toggles slim (3 px) arms |
| `@pose JOINT X Y Z` | Sets a joint's angles in degrees (root, neck, shoulderR, shoulderL, hipR, hipL) or the root offset in pixels (rootPos) |
| `@pose reset` | Sets all joints back to rest |
| `@pack` | Sends the resource pack again |

## Files

| Path | Contents |
| --- | --- |
| [tc/](tc/) | Plot code: the rig (`rig.tc`), commands and events (`commands.tc`), the pack (`pack.tc`) |
| [pack/](pack/) | The resource pack: the skin-part shader and the `combat:body/unit` item model |
| [tools/build_pack.py](tools/build_pack.py) | Validates the pack, compiles its shaders, builds the zip, and publishes it to the `pack-dist` branch (`--publish --push`) |
