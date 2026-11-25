"""Author the Phase 0 reference scene: two characters, one living room, 32 seconds."""

from __future__ import annotations

import json
from pathlib import Path

from cuervo_ir.models import (
    ActionKeyframe,
    ActionTrack,
    Actor,
    AssetLibrary,
    AssetRef,
    BackgroundAsset,
    Camera,
    CharacterAsset,
    DialogueTrack,
    Episode,
    PropAsset,
    Provenance,
    RigAsset,
    Scene,
    Shot,
    TimingPatch,
    Transform,
)

FPS = 24
TARGET_FRAMES = 768  # 32 seconds

ROOT = Path(__file__).resolve().parent
EPISODE_PATH = ROOT / "reference-scene.json"
PATCH_PATH = ROOT / "hold-reaction-12.patch.json"


def build_reference_episode() -> Episode:
    assets = AssetLibrary(
        characters=[
            CharacterAsset(
                asset_id="char_nia",
                version="1.0.0",
                display_name="Nia Adeyemi",
                rig_id="rig_nia",
                rig_version="1.0.0",
                extension_poses=["deadpan"],
            ),
            CharacterAsset(
                asset_id="char_cole",
                version="1.0.0",
                display_name="Cole Park",
                rig_id="rig_cole",
                rig_version="1.0.0",
                extension_poses=["fidget"],
            ),
        ],
        rigs=[
            RigAsset(asset_id="rig_nia", version="1.0.0", character_id="char_nia"),
            RigAsset(asset_id="rig_cole", version="1.0.0", character_id="char_cole"),
        ],
        backgrounds=[
            BackgroundAsset(
                asset_id="bg_living_room",
                version="1.0.0",
                display_name="Nia's living room",
                location_id="loc_living_room",
            )
        ],
        props=[
            PropAsset(asset_id="prop_couch", version="1.0.0", display_name="Couch"),
            PropAsset(asset_id="prop_coffee_table", version="1.0.0", display_name="Coffee table"),
            PropAsset(asset_id="prop_television", version="1.0.0", display_name="Television"),
            PropAsset(asset_id="prop_remote", version="1.0.0", display_name="Remote"),
        ],
    )
    scene_id = "sc_five_minutes"
    shots = [
        _shot(
            "sh_establish",
            scene_id,
            start=0,
            duration=96,
            preset="wide",
            framing="Both characters on the couch, television off, full living room",
            camera_at=(0, 80),
            camera_scale=1,
            action=[
                _body("tr_est_nia_sit", "act_nia", 96, "sit"),
                _body("tr_est_cole_sit", "act_cole", 96, "sit"),
                _blink("tr_est_nia_blink", "act_nia", 36, 48),
            ],
            dialogue=[],
            constraints=["show the full couch, both lamps, and the television"],
        ),
        _shot(
            "sh_two_shot",
            scene_id,
            start=96,
            duration=312,
            preset="two_shot",
            framing="Nia and Cole, waist up, couch",
            camera_at=(0, 140),
            camera_scale=1.4,
            action=[
                _body("tr_two_nia_sit", "act_nia", 312, "sit"),
                _body("tr_two_cole_sit", "act_cole", 312, "sit"),
                _gesture("tr_two_cole_shrug", "act_cole", 24, 84, "shrug"),
                _expression("tr_two_nia_deadpan", "act_nia", 108, 240, "deadpan"),
                _gesture("tr_two_cole_point", "act_cole", 252, 300, "point"),
            ],
            dialogue=[
                _line("tr_ln_five", "ln_five", "act_cole", "You said five minutes.", 24, 84),
                _line(
                    "tr_ln_quiet",
                    "ln_quiet",
                    "act_nia",
                    "I said five minutes of quiet. You used four of them finding the remote.",
                    108,
                    240,
                ),
                _line("tr_ln_remote", "ln_remote", "act_cole", "It's under you.", 252, 300),
            ],
            constraints=["hold both characters at waist-up"],
        ),
        _shot(
            "sh_reaction",
            scene_id,
            start=408,
            duration=144,
            preset="close_up",
            framing="Nia, head and shoulders, holding the reaction",
            camera_at=(-180, 180),
            camera_scale=2.2,
            action=[
                _body("tr_react_nia_sit", "act_nia", 144, "sit"),
                _body("tr_react_cole_sit", "act_cole", 144, "sit"),
                _expression("tr_nia_react", "act_nia", 72, 144, "react"),
            ],
            dialogue=[
                _line("tr_ln_nothing", "ln_nothing", "act_nia", "Then we watch nothing.", 0, 72),
            ],
            constraints=["Nia stays on the left-cushion eyeline"],
        ),
        _shot(
            "sh_button",
            scene_id,
            start=552,
            duration=216,
            preset="two_shot",
            framing="Both look at the dark television",
            camera_at=(0, 140),
            camera_scale=1.4,
            action=[
                _body("tr_btn_nia_sit", "act_nia", 216, "sit"),
                _body("tr_btn_cole_sit", "act_cole", 216, "sit"),
                _gaze("tr_btn_nia_look", "act_nia", 120, 216),
                _gaze("tr_btn_cole_look", "act_cole", 120, 216),
                _expression("tr_btn_nia_hold", "act_nia", 120, 216, "hold"),
            ],
            dialogue=[
                _line(
                    "tr_ln_plan",
                    "ln_plan",
                    "act_cole",
                    "That's the plan I had before I sat down.",
                    12,
                    108,
                ),
            ],
            constraints=["eyelines meet the television, which stays off"],
        ),
    ]
    return Episode(
        kind="episode",
        episode_id="ep_five_minutes",
        version="0.1.0",
        title="Five Minutes",
        fps=FPS,
        assets=assets,
        scenes=[
            Scene(
                scene_id=scene_id,
                episode_id="ep_five_minutes",
                title="Five Minutes",
                objective="Nia and Cole sit down to watch something and never turn the television on.",
                setting_id="bg_living_room",
                emotional_trajectory="mild annoyance settling into a shared deadpan truce",
                continuity=[
                    "Evening. Both lamps are on. The television stays off.",
                    "Nia sits on the left cushion. Cole sits on the right cushion.",
                    "The remote stays under Nia's cushion.",
                    "Neither character stands or leaves the couch.",
                ],
                target_runtime_frames=TARGET_FRAMES,
                shots=shots,
            )
        ],
    )


def build_hold_reaction_patch() -> TimingPatch:
    """The blueprint's example: hold the reaction 12 more frames."""

    return TimingPatch(
        kind="timing_patch",
        patch_id="patch_hold_reaction_12",
        target_shot_id="sh_reaction",
        base_revision="rev-0001",
        reason="Hold the reaction 12 more frames.",
        timing=[{"track_id": "tr_nia_react", "end_delta_frames": 12}],
        extend_shot_frames=12,
    )


def write_examples() -> None:
    episode = build_reference_episode()
    patch = build_hold_reaction_patch()
    EPISODE_PATH.write_text(episode.model_dump_json(indent=2) + "\n", encoding="utf-8")
    PATCH_PATH.write_text(patch.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _shot(
    shot_id,
    scene_id,
    start,
    duration,
    preset,
    framing,
    camera_at,
    camera_scale,
    action,
    dialogue,
    constraints,
) -> Shot:
    return Shot(
        shot_id=shot_id,
        scene_id=scene_id,
        fps=FPS,
        start_frame=start,
        duration_frames=duration,
        asset_refs=_asset_refs(),
        camera=Camera(
            preset=preset,
            framing=framing,
            transform=Transform(space="camera", unit="px", x=camera_at[0], y=camera_at[1], scale=camera_scale),
            constraints=constraints,
        ),
        actors=[_actor("act_nia", "char_nia", "rig_nia", "riginst_nia", -180), _actor("act_cole", "char_cole", "rig_cole", "riginst_cole", 180)],
        action_tracks=action,
        dialogue_tracks=dialogue,
        locks=[],
        provenance=Provenance(
            revision="rev-0001",
            source="authored",
            note="Phase 0 reference scene, authored against the rig contract.",
        ),
    )


def _asset_refs() -> list[AssetRef]:
    pins = [
        ("character", "char_nia"),
        ("character", "char_cole"),
        ("rig", "rig_nia"),
        ("rig", "rig_cole"),
        ("background", "bg_living_room"),
        ("prop", "prop_couch"),
        ("prop", "prop_coffee_table"),
        ("prop", "prop_television"),
        ("prop", "prop_remote"),
    ]
    return [AssetRef(role=role, asset_id=asset_id, version="1.0.0") for role, asset_id in pins]


def _actor(actor_id, character_id, rig_id, instance_id, x) -> Actor:
    facing = "three_quarter_right" if actor_id == "act_nia" else "three_quarter_left"
    return Actor(
        actor_id=actor_id,
        character_id=character_id,
        rig_id=rig_id,
        rig_instance_id=instance_id,
        stage=Transform(space="stage", unit="px", x=x, y=40),
        facing=facing,
        depth=2,
        visible=True,
    )


def _body(track_id, actor_id, duration, pose) -> ActionTrack:
    return ActionTrack(
        track_id=track_id,
        kind="pose",
        target_actor_id=actor_id,
        start_frame=0,
        end_frame=duration,
        interpolation="stepped",
        mask=["root", "torso", "leg_l", "leg_r"],
        priority=10,
        blend_mode="override",
        keyframes=[ActionKeyframe(frame=0, pose=pose)],
    )


def _blink(track_id, actor_id, start, end) -> ActionTrack:
    return ActionTrack(
        track_id=track_id,
        kind="secondary",
        target_actor_id=actor_id,
        start_frame=start,
        end_frame=end,
        interpolation="stepped",
        mask=["blink"],
        priority=50,
        blend_mode="override",
        keyframes=[ActionKeyframe(frame=start, pose="blink")],
    )


def _gesture(track_id, actor_id, start, end, pose) -> ActionTrack:
    return ActionTrack(
        track_id=track_id,
        kind="gesture",
        target_actor_id=actor_id,
        start_frame=start,
        end_frame=end,
        interpolation="ease_in_out",
        mask=["arm_l", "arm_r", "hand_l", "hand_r"],
        priority=20,
        blend_mode="override",
        keyframes=[ActionKeyframe(frame=start, pose=pose)],
    )


def _expression(track_id, actor_id, start, end, pose) -> ActionTrack:
    return ActionTrack(
        track_id=track_id,
        kind="expression",
        target_actor_id=actor_id,
        start_frame=start,
        end_frame=end,
        interpolation="stepped",
        mask=["brow_l", "brow_r", "eye_l", "eye_r", "mouth"],
        priority=40,
        blend_mode="override",
        keyframes=[ActionKeyframe(frame=start, pose=pose)],
    )


def _gaze(track_id, actor_id, start, end) -> ActionTrack:
    return ActionTrack(
        track_id=track_id,
        kind="gaze",
        target_actor_id=actor_id,
        start_frame=start,
        end_frame=end,
        interpolation="ease_in_out",
        mask=["gaze_yaw", "gaze_pitch", "head"],
        priority=30,
        blend_mode="override",
        keyframes=[ActionKeyframe(frame=start, pose="look_at")],
    )


def _line(track_id, line_id, actor_id, text, start, end) -> DialogueTrack:
    return DialogueTrack(
        track_id=track_id,
        speaker_actor_id=actor_id,
        line_id=line_id,
        text=text,
        start_frame=start,
        end_frame=end,
    )


if __name__ == "__main__":
    write_examples()
    print(json.dumps({"episode": str(EPISODE_PATH), "patch": str(PATCH_PATH)}))
