"""Generic episodes for engine tests. Not a series."""

from __future__ import annotations

from cuervo_ir.models import (
    ActionKeyframe,
    ActionTrack,
    Actor,
    AssetLibrary,
    AssetRef,
    BackgroundAsset,
    Camera,
    CharacterAsset,
    Episode,
    Provenance,
    RigAsset,
    Scene,
    Shot,
    TimingPatch,
    Transform,
)


def solo_episode() -> Episode:
    actor = Actor(
        actor_id="act_a",
        character_id="char_a",
        rig_id="rig_a",
        rig_instance_id="riginst_a",
        stage=Transform(space="stage", unit="px", x=0, y=0),
        facing="front",
        depth=1,
    )
    track = ActionTrack(
        track_id="tr_hold",
        kind="expression",
        target_actor_id="act_a",
        start_frame=0,
        end_frame=24,
        interpolation="stepped",
        mask=["mouth"],
        priority=40,
        blend_mode="override",
        keyframes=[ActionKeyframe(frame=0, pose="hold")],
    )
    shot = Shot(
        shot_id="sh_a",
        scene_id="sc_a",
        fps=24,
        start_frame=0,
        duration_frames=24,
        asset_refs=[
            AssetRef(role="character", asset_id="char_a", version="1.0.0"),
            AssetRef(role="rig", asset_id="rig_a", version="1.0.0"),
            AssetRef(role="background", asset_id="bg_a", version="1.0.0"),
        ],
        camera=Camera(
            preset="wide",
            framing="single figure",
            transform=Transform(space="camera", unit="px", x=0, y=0),
        ),
        actors=[actor],
        action_tracks=[track],
        dialogue_tracks=[],
        provenance=Provenance(revision="rev-0001", source="authored", note="engine fixture"),
    )
    return Episode(
        kind="episode",
        episode_id="ep_a",
        version="0.1.0",
        title="Fixture",
        fps=24,
        assets=AssetLibrary(
            characters=[
                CharacterAsset(
                    asset_id="char_a",
                    version="1.0.0",
                    display_name="Figure A",
                    rig_id="rig_a",
                    rig_version="1.0.0",
                )
            ],
            rigs=[RigAsset(asset_id="rig_a", version="1.0.0", character_id="char_a")],
            backgrounds=[
                BackgroundAsset(
                    asset_id="bg_a",
                    version="1.0.0",
                    display_name="Empty stage",
                    location_id="loc_a",
                )
            ],
        ),
        scenes=[
            Scene(
                scene_id="sc_a",
                episode_id="ep_a",
                title="Fixture",
                objective="Hold.",
                setting_id="bg_a",
                emotional_trajectory="still",
                continuity=[],
                target_runtime_frames=24,
                shots=[shot],
            )
        ],
    )


def hold_patch() -> TimingPatch:
    return TimingPatch(
        kind="timing_patch",
        patch_id="patch_hold",
        target_shot_id="sh_a",
        base_revision="rev-0001",
        reason="Hold 12 more frames.",
        timing=[{"track_id": "tr_hold", "end_delta_frames": 12}],
        extend_shot_frames=12,
    )
