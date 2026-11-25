"""Dev stand-in used only when CUERVO_EDITOR_STUB=1.

It is still a router provider for the ir_patch step. It is not a series.
"""

from __future__ import annotations

import json

from cuervo_ir.providers.router import ModelRequest, ModelResponse


class DevStub:
    name = "devstub"

    def available(self) -> bool:
        return True

    def complete(self, request: ModelRequest) -> ModelResponse:
        payload = json.loads(request.user)
        instruction = str(payload["instruction"]).lower()
        tracks = payload["tracks"]
        base = {
            "kind": "edit_patch",
            "patch_id": "patch_devstub",
            "target_shot_id": payload["target_shot_id"],
            "base_revision": payload["base_revision"],
            "reason": payload["instruction"],
        }
        if "hold" in instruction and tracks:
            base["timing"] = [{"track_id": tracks[0]["track_id"], "end_delta_frames": 12}]
            base["extend_shot_frames"] = 12
        elif "close" in instruction:
            base["camera"] = {"preset": "close_up", "x": 40}
        else:
            track = next((item for item in tracks if item["kind"] == "expression"), tracks[0] if tracks else None)
            if track is None:
                base["camera"] = {"preset": "close_up"}
            else:
                pose = "react" if "react" in track["allowed_poses"] else track["allowed_poses"][0]
                base["poses"] = [{"track_id": track["track_id"], "pose": pose}]
        return ModelResponse(provider=self.name, model="devstub", text=json.dumps(base))
