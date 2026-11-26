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

The built-in art is the house style: flat color and one even line, drawn from the design by code.

To use art from an illustrator or an image model, replace the PNG files in a character's version folder. Keep each part's size and pivot as `rig.json` gives them, or edit `rig.json` to match. Do this while the asset is a draft, then approve it.

## Painted sets and characters

Put one or more models on the **Image generation** role and the world is also painted by image models. Gemini and OpenAI image models are supported. Every model gets the same prompt, built from the design.

**Sets.** Each model paints the set as one background plate. The picture is cropped to 16:9 and kept beside the house-style plate. The first painted picture is used until someone picks another.

**Characters.** Each model paints the character once: standing, facing the viewer, arms held away from the body, legs apart, on a plain background. Cuervo then cuts that one picture into the animated parts.

1. The background is cleared by filling in from the edges, so a white shirt or the whites of the eyes are kept.
2. The arms are found where the figure is in three pieces, and the legs where the body is in two.
3. The figure is cut at the neck, shoulders, elbows, hips, and knees, and the rig is measured from those cuts.
4. The painted face is kept. A blink and a spoken mouth are drawn over it on a patch of the character's own skin color.

A picture that cannot be cut is not offered, and the build log says why: the arms touch the body, the legs are together, or there is no figure. The house style stays in use until someone looks at the painted model sheet and picks it. A painted character faces the viewer, so it looks the same turned left or right.

Picking a different look, for a set or a character, redraws the shots that use it. An approved asset must be reopened before its look can change. The reference picture each model painted is kept beside its parts as `reference.png`.

The eyes and mouth of a painted face are placed by proportion, at about half and three quarters of the way down the head. If they sit wrong on a particular picture, edit the `face` positions in that candidate's `rig.json`.

The two image adapters are tested against the documented response shapes, and the cutter against a drawn stand-in figure. Neither has been run on a real image model's picture from this repo. Only the three-quarter view of a character is built. Front, side, and back views are not.
