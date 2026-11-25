"""Common rig contract for Phase 0.

Character-specific poses and controllers are extensions on the character
asset. Tracks may use a standard name or one of those extensions. They may
not invent controllers outside that set.
"""

from __future__ import annotations

CONTRACT_ID = "cuervo.rig.v0"

# Section 4 of the blueprint: a shared controller set, with room for
# character-specific extensions stored on the character asset.
STANDARD_CONTROLLERS: tuple[str, ...] = (
    "root",
    "torso",
    "head",
    "neck",
    "eye_l",
    "eye_r",
    "blink",
    "brow_l",
    "brow_r",
    "jaw",
    "mouth",
    "arm_l",
    "arm_r",
    "hand_l",
    "hand_r",
    "leg_l",
    "leg_r",
    "gaze_yaw",
    "gaze_pitch",
)

MOUTH_CONTROLLERS: tuple[str, ...] = ("jaw", "mouth")
EYE_CONTROLLERS: tuple[str, ...] = ("eye_l", "eye_r", "blink", "brow_l", "brow_r", "gaze_yaw", "gaze_pitch")

# Normalized controller space. 0 is rest. Limits are inclusive.
CONTROLLER_LIMITS: dict[str, tuple[float, float]] = {name: (-1.0, 1.0) for name in STANDARD_CONTROLLERS}
CONTROLLER_LIMITS["blink"] = (0.0, 1.0)
CONTROLLER_LIMITS["jaw"] = (0.0, 1.0)
CONTROLLER_LIMITS["mouth"] = (0.0, 1.0)

# Section 5: the approved action library this contract requires every rig to ship.
REQUIRED_POSES: tuple[str, ...] = (
    "idle",
    "blink",
    "nod",
    "look_at",
    "shrug",
    "point",
    "walk",
    "sit",
    "stand",
    "react",
    "recoil",
    "hold",
)

REQUIRED_VIEWS: tuple[str, ...] = ("front", "three_quarter", "side", "back")


def allowed_poses(extension_poses: tuple[str, ...] | list[str]) -> set[str]:
    return set(REQUIRED_POSES).union(extension_poses)


def allowed_controllers(extension_controllers: tuple[str, ...] | list[str]) -> set[str]:
    return set(STANDARD_CONTROLLERS).union(extension_controllers)
