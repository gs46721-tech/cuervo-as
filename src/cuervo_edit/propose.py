"""Ask the model router for one typed edit. The router picks Claude, then Gemini, then Cursor."""

from __future__ import annotations

import json

from cuervo_ir.contract import allowed_poses
from cuervo_ir.models import Episode
from cuervo_ir.providers.router import ModelRequest, ProviderRouter
from cuervo_edit.edits import EditError, EditPatch, _shot


SYSTEM = (
    "You revise one shot of an animation episode. Return only an edit_patch JSON object. "
    "Change timing, an existing track pose, or the camera. Do not invent shots, actors, "
    "or rig controls. Do not edit a locked track. Leave every other shot alone."
)


def propose_edit(episode: Episode, shot_id: str, instruction: str, router: ProviderRouter) -> EditPatch:
    shot = _shot(episode, shot_id)
    characters = {item.asset_id: item for item in episode.assets.characters}
    tracks = []
    for track in shot.action_tracks:
        actor = next(actor for actor in shot.actors if actor.actor_id == track.target_actor_id)
        character = characters[actor.character_id]
        tracks.append(
            {
                "track_id": track.track_id,
                "kind": track.kind,
                "actor_id": actor.actor_id,
                "allowed_poses": sorted(allowed_poses(character.extension_poses)),
            }
        )
    response = router.complete(
        ModelRequest(
            step="ir_patch",
            system=SYSTEM,
            user=json.dumps(
                {
                    "instruction": instruction,
                    "target_shot_id": shot.shot_id,
                    "base_revision": shot.provenance.revision,
                    "tracks": tracks,
                    "camera_preset": shot.camera.preset,
                    "locks": [lock.model_dump(mode="json") for lock in shot.locks],
                }
            ),
            response_schema=EditPatch.model_json_schema(),
        )
    )
    try:
        payload = json.loads(_strip_fence(response.text))
        patch = EditPatch.model_validate(payload)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise EditError(f"{response.provider} did not return an edit patch") from exc
    if patch.target_shot_id != shot_id:
        raise EditError(f"patch targeted {patch.target_shot_id}, not {shot_id}")
    if patch.base_revision != shot.provenance.revision:
        raise EditError("patch revision does not match the shot")
    return patch


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped.split("\n", 1)[1]
    return body.rsplit("```", 1)[0]
