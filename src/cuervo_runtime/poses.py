"""Default controller values for the shared rig contract.

A series adds poses by passing its own table. Those names are not known here.
"""

from __future__ import annotations

from cuervo_ir.contract import CONTROLLER_LIMITS, REQUIRED_POSES

CONTRACT_POSES: dict[str, dict[str, float]] = {
    "idle": {},
    "blink": {"blink": 1.0},
    "nod": {"head": 0.4},
    "look_at": {"gaze_yaw": 0.5, "head": 0.2},
    "shrug": {"arm_l": 0.6, "arm_r": 0.6},
    "point": {"arm_r": 0.8, "hand_r": 0.5},
    "walk": {"leg_l": 0.4, "leg_r": -0.4},
    "sit": {"leg_l": -0.6, "leg_r": -0.6, "torso": 0.1},
    "stand": {},
    "react": {"brow_l": 0.7, "brow_r": 0.7, "mouth": 0.4},
    "recoil": {"torso": -0.4, "head": -0.3},
    "hold": {"mouth": 0.15},
}


class UnknownPose(ValueError):
    pass


def resolve_pose(name: str, library: dict[str, dict[str, float]] | None) -> dict[str, float]:
    if library and name in library:
        return library[name]
    if name in CONTRACT_POSES:
        return CONTRACT_POSES[name]
    raise UnknownPose(name)


def clamp_controls(values: dict[str, float]) -> dict[str, float]:
    clamped = {}
    for name, (low, high) in CONTROLLER_LIMITS.items():
        clamped[name] = min(high, max(low, values.get(name, 0.0)))
    return clamped


assert set(CONTRACT_POSES) == set(REQUIRED_POSES)
