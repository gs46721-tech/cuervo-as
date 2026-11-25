# Rig contract `cuervo.rig.v0`

Artist-authored master rigs share this contract. A character may add poses and controllers. A track that names anything outside the contract plus that character's extensions is invalid. Constants live in `src/cuervo_ir/contract.py`.

## Required views

Front, three-quarter, side, and back, where the pose is used. The reference scene only instances three-quarter views: Nia faces right, Cole faces left.

## Controllers

Normalized, rest at 0, unless noted. Limits are inclusive.

| Controller | Limit | Notes |
| --- | --- | --- |
| `root`, `torso`, `head`, `neck` | -1 to 1 | Body placement and orientation |
| `arm_l`, `arm_r`, `hand_l`, `hand_r` | -1 to 1 | Gestures |
| `leg_l`, `leg_r` | -1 to 1 | Seated or standing base |
| `eye_l`, `eye_r`, `brow_l`, `brow_r` | -1 to 1 | Eyes and brows |
| `gaze_yaw`, `gaze_pitch` | -1 to 1 | Eyeline, separate from the head |
| `blink` | 0 to 1 | 0 open, 1 closed |
| `jaw`, `mouth` | 0 to 1 | Mouth shapes. Viseme mapping is a later slice |

## Required poses

`idle`, `blink`, `nod`, `look_at`, `shrug`, `point`, `walk`, `sit`, `stand`, `react`, `recoil`, `hold`.

Reference extensions, which are not part of the shared library:

- Nia: `deadpan`
- Cole: `fidget`

## Draw order

Head, eyes, and mouth draw above the torso. Near arm draws above the torso; far arm draws behind it when the view calls for it. Held props draw in the hand that the gesture names. The reference scene holds no prop in a hand. The remote stays under the cushion and is pinned so the continuity fact has an asset.
