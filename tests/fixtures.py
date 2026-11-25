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


def _track(track_id: str, kind: str, end: int, pose: str, mask: list[str], priority: int) -> ActionTrack:
    return ActionTrack(
        track_id=track_id,
        kind=kind,
        target_actor_id="act_a",
        start_frame=0,
        end_frame=end,
        interpolation="stepped",
        mask=mask,
        priority=priority,
        blend_mode="override",
        keyframes=[ActionKeyframe(frame=0, pose=pose)],
    )


def stage_episode() -> Episode:
    """Two shots and four track kinds. Not a series."""

    episode = solo_episode()
    episode.scenes[0].target_runtime_frames = 72
    main = episode.scenes[0].shots[0]
    main.shot_id = "sh_main"
    main.duration_frames = 48
    main.action_tracks = [
        _track("tr_body", "pose", 48, "sit", ["root", "torso"], 10),
        _track("tr_gesture", "gesture", 24, "shrug", ["arm_r", "hand_r"], 20),
        _track("tr_gaze", "gaze", 48, "idle", ["gaze_yaw", "head"], 30),
        _track("tr_face", "expression", 48, "hold", ["mouth", "brow_l"], 40),
    ]
    main.camera.preset = "wide"
    follower = main.model_copy(deep=True)
    follower.shot_id = "sh_next"
    follower.start_frame = 48
    follower.duration_frames = 24
    follower.action_tracks = [_track("tr_next_body", "pose", 24, "sit", ["root", "torso"], 10)]
    follower.camera.preset = "two_shot"
    episode.scenes[0].shots = [main, follower]
    return Episode.model_validate(episode.model_dump())


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
