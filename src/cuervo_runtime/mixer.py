"""Sample action tracks into one controller vector per actor at one frame."""

from __future__ import annotations

from cuervo_ir.models import ActionTrack, Shot

from cuervo_runtime.poses import clamp_controls, resolve_pose


def controls_at(
    shot: Shot,
    actor_id: str,
    frame: int,
    library: dict[str, dict[str, float]] | None = None,
) -> dict[str, float]:
    values = clamp_controls({})
    layered: list[tuple[int, str, list[str], dict[str, float]]] = []
    for track in shot.action_tracks:
        if track.target_actor_id != actor_id:
            continue
        if frame < track.start_frame or frame >= track.end_frame:
            continue
        layered.append((track.priority, track.blend_mode, list(track.mask), _pose_values(track, frame, library)))
    for _priority, blend, mask, pose_values in sorted(layered, key=lambda item: item[0]):
        for controller in mask:
            incoming = pose_values.get(controller, 0.0)
            if blend == "additive":
                values[controller] = values.get(controller, 0.0) + incoming
            else:
                values[controller] = incoming
    return clamp_controls(values)


def _pose_values(track: ActionTrack, frame: int, library) -> dict[str, float]:
    keys = sorted(track.keyframes, key=lambda key: key.frame)
    chosen = keys[0]
    for key in keys:
        if key.frame <= frame:
            chosen = key
            continue
        if track.interpolation == "stepped":
            break
        span = key.frame - chosen.frame
        if span <= 0:
            break
        weight = _ease((frame - chosen.frame) / span, track.interpolation)
        start = resolve_pose(chosen.pose, library)
        end = resolve_pose(key.pose, library)
        names = set(start) | set(end)
        return {name: start.get(name, 0.0) + (end.get(name, 0.0) - start.get(name, 0.0)) * weight for name in names}
    return resolve_pose(chosen.pose, library)


def _ease(weight: float, interpolation: str) -> float:
    if interpolation == "ease_in_out":
        return weight * weight * (3 - 2 * weight)
    return weight
