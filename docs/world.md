# The world

Cuervo is 2D only. A character is not drawn again for each frame. Every character and every set is designed once, built once, approved, and then animated. That is what keeps a show on model from the first shot to the last.

## Design, build, approve, animate

1. **Design.** Each character and set has a design in the series kit: colors, hair, build, height, furniture, time of day. See `examples/sample-series/series.json`.
2. **Build.** The world is built from those designs before any shot is animated.
3. **Approve.** A model sheet shows the character in the standard poses and all eight mouths. Approving it freezes the look.
4. **Animate.** Every frame is composed from the approved parts. The pipeline and the editor draw from the same files.

```bash
python3 -m cuervo_world build examples/sample-series/series.json --out world/
python3 -m cuervo_world list world/
python3 -m cuervo_world approve world/ char_nia
```

`produce` builds whatever is missing into `<out>/world`, or into the folder you pass with `--world`. In the editor, **World: cast and sets** shows every model sheet and set with an Approve button.

## What is on disk

```
world/
  world.json                          every asset, its version, and whether it is approved
  characters/<id>/<version>/          the parts, rig.json, and sheet.png
  sets/<id>/<version>/plate.png
```

A character is these parts: torso, head, upper arm, forearm with hand, thigh, shin with shoe, an open eye, a closed eye, a brow, and one mouth for each viseme (`rest`, `MBP`, `FV`, `TH`, `AA`, `EE`, `OH`, `L`). `rig.json` gives each part's size and pivot and says where the shoulders, hips, neck, and face features sit.

A set is one plate, three times the frame width, so the camera can push in and pan without the picture going soft.

## How a frame is drawn

The rig controllers turn and slide the parts about their pivots: an arm about the shoulder, a forearm about the elbow, a thigh about the hip. Past a walking stride the knee bends and the hips drop, which is a sit. A blink swaps the eye. Speech swaps the mouth to the viseme for that frame. A character facing left is the same art mirrored.

Nothing in a frame is generated. The same head and the same hands appear every time, so a character cannot drift.

## Versions

- A draft can be rebuilt in place when its design changes.
- An approved asset is frozen. If its design changes, the build stops and asks for a new version in the kit.
- A new version is built beside the old one. Shots pin a version, so finished shots keep their look until someone repins them.
- The render cache includes the art a shot uses. New art redraws only the shots that use it.

## Bringing your own art

The built-in art is the house style: flat color and one even line, drawn from the design by code. No model call is involved.

To use art from an illustrator or an image model, replace the PNG files in a character's version folder. Keep each part's size and pivot as `rig.json` gives them, or edit `rig.json` to match. Do this while the asset is a draft, then approve it.

Cuervo does not call an image model to generate art. Only the three-quarter view is built. Front, side, and back views are not.
