"""Animation IR v0.

Timeline time is integer frames. A track occupies the half-open interval
[start_frame, end_frame). Shot duration is a frame count on the scene
timeline, starting at start_frame.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cuervo_ir.contract import CONTRACT_ID, allowed_controllers, allowed_poses

Id = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
Version = Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
Revision = Annotated[str, Field(pattern=r"^rev-[0-9]{4,}$")]
Frame = Annotated[int, Field(ge=0)]

CameraPreset = Literal[
    "wide",
    "two_shot",
    "over_the_shoulder",
    "close_up",
    "reaction",
    "insert",
]
Facing = Literal[
    "front",
    "three_quarter_left",
    "three_quarter_right",
    "side_left",
    "side_right",
    "back",
]
ActionKind = Literal["pose", "gesture", "gaze", "expression", "locomotion", "secondary"]
Interpolation = Literal["stepped", "linear", "ease_in_out"]
BlendMode = Literal["override", "additive"]
AssetRole = Literal["character", "rig", "background", "prop"]
LockProperty = Literal["timing", "pose", "camera", "dialogue"]
CoordinateSpace = Literal["stage", "camera", "local"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Transform(StrictModel):
    space: CoordinateSpace
    unit: Literal["px"]
    x: float
    y: float
    rotation_deg: float = 0
    scale: float = Field(default=1, gt=0)


class AssetRef(StrictModel):
    role: AssetRole
    asset_id: Id
    version: Version


class CameraKeyframe(StrictModel):
    frame: Frame
    transform: Transform


class Camera(StrictModel):
    preset: CameraPreset
    framing: Annotated[str, Field(min_length=1)]
    transform: Transform
    keyframes: list[CameraKeyframe] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class Actor(StrictModel):
    actor_id: Id
    character_id: Id
    rig_id: Id
    rig_instance_id: Id
    stage: Transform
    facing: Facing
    depth: int
    visible: bool = True


class ActionKeyframe(StrictModel):
    frame: Frame
    pose: Id
    weight: float = Field(default=1, ge=0, le=1)


class ActionTrack(StrictModel):
    track_id: Id
    kind: ActionKind
    target_actor_id: Id
    start_frame: Frame
    end_frame: Frame
    interpolation: Interpolation
    mask: Annotated[list[Id], Field(min_length=1)]
    priority: Annotated[int, Field(ge=0, le=100)]
    blend_mode: BlendMode
    keyframes: Annotated[list[ActionKeyframe], Field(min_length=1)]

    @model_validator(mode="after")
    def interval(self) -> ActionTrack:
        if self.end_frame <= self.start_frame:
            raise ValueError(f"{self.track_id}: end_frame must be greater than start_frame")
        for key in self.keyframes:
            if key.frame < self.start_frame or key.frame >= self.end_frame:
                raise ValueError(f"{self.track_id}: keyframe {key.frame} is outside the track")
        return self


class DialogueTrack(StrictModel):
    track_id: Id
    speaker_actor_id: Id
    line_id: Id
    text: Annotated[str, Field(min_length=1)]
    voice_take_id: Id | None = None
    voice_take_version: Version | None = None
    start_frame: Frame
    end_frame: Frame
    # Populated by the voice slice. Phase 0 stores the fields and keeps them empty.
    alignment: Annotated[list[object], Field(max_length=0)] = Field(default_factory=list)
    visemes: Annotated[list[object], Field(max_length=0)] = Field(default_factory=list)

    @model_validator(mode="after")
    def interval_and_voice(self) -> DialogueTrack:
        if self.end_frame <= self.start_frame:
            raise ValueError(f"{self.track_id}: end_frame must be greater than start_frame")
        if (self.voice_take_id is None) != (self.voice_take_version is None):
            raise ValueError(f"{self.track_id}: voice take id and version are set together")
        return self


class Lock(StrictModel):
    lock_id: Id
    target_track_id: Id
    properties: Annotated[list[LockProperty], Field(min_length=1)]


class Provenance(StrictModel):
    revision: Revision
    parent_revision: Revision | None = None
    source: Annotated[str, Field(min_length=1)]
    note: Annotated[str, Field(min_length=1)]


class Shot(StrictModel):
    shot_id: Id
    scene_id: Id
    fps: Annotated[int, Field(ge=1, le=60)]
    start_frame: Frame
    duration_frames: Annotated[int, Field(ge=1)]
    asset_refs: Annotated[list[AssetRef], Field(min_length=1)]
    camera: Camera
    actors: Annotated[list[Actor], Field(min_length=1)]
    action_tracks: list[ActionTrack]
    dialogue_tracks: list[DialogueTrack]
    locks: list[Lock] = Field(default_factory=list)
    provenance: Provenance

    @model_validator(mode="after")
    def tracks_fit_shot(self) -> Shot:
        _unique([actor.actor_id for actor in self.actors], "actor_id")
        _unique([track.track_id for track in self.action_tracks], "action track_id")
        _unique([track.track_id for track in self.dialogue_tracks], "dialogue track_id")
        _unique([track.line_id for track in self.dialogue_tracks], "line_id")
        actor_ids = {actor.actor_id for actor in self.actors}
        known_tracks = {track.track_id for track in self.action_tracks}
        known_tracks.update(track.track_id for track in self.dialogue_tracks)
        for track in self.action_tracks:
            if track.target_actor_id not in actor_ids:
                raise ValueError(f"{track.track_id} targets unknown actor {track.target_actor_id}")
            if track.end_frame > self.duration_frames:
                raise ValueError(f"{track.track_id} extends past the shot")
        for track in self.dialogue_tracks:
            if track.speaker_actor_id not in actor_ids:
                raise ValueError(f"{track.track_id} speaks from unknown actor {track.speaker_actor_id}")
            if track.end_frame > self.duration_frames:
                raise ValueError(f"{track.track_id} extends past the shot")
        _reject_overlapping_dialogue(self.dialogue_tracks)
        _reject_ambiguous_mix(self.action_tracks)
        for lock in self.locks:
            if lock.target_track_id not in known_tracks:
                raise ValueError(f"{lock.lock_id} locks unknown track {lock.target_track_id}")
        for key in self.camera.keyframes:
            if key.frame >= self.duration_frames:
                raise ValueError(f"{self.shot_id}: camera keyframe {key.frame} is outside the shot")
        return self


class CharacterAsset(StrictModel):
    asset_id: Id
    version: Version
    display_name: Annotated[str, Field(min_length=1)]
    rig_id: Id
    rig_version: Version
    extension_poses: list[Id] = Field(default_factory=list)
    extension_controllers: list[Id] = Field(default_factory=list)


class RigAsset(StrictModel):
    asset_id: Id
    version: Version
    character_id: Id
    contract: Literal["cuervo.rig.v0"] = CONTRACT_ID


class BackgroundAsset(StrictModel):
    asset_id: Id
    version: Version
    display_name: Annotated[str, Field(min_length=1)]
    location_id: Id


class PropAsset(StrictModel):
    asset_id: Id
    version: Version
    display_name: Annotated[str, Field(min_length=1)]


class AssetLibrary(StrictModel):
    characters: Annotated[list[CharacterAsset], Field(min_length=1)]
    rigs: Annotated[list[RigAsset], Field(min_length=1)]
    backgrounds: Annotated[list[BackgroundAsset], Field(min_length=1)]
    props: list[PropAsset] = Field(default_factory=list)


class Scene(StrictModel):
    scene_id: Id
    episode_id: Id
    title: Annotated[str, Field(min_length=1)]
    objective: Annotated[str, Field(min_length=1)]
    setting_id: Id
    emotional_trajectory: Annotated[str, Field(min_length=1)]
    continuity: list[str]
    target_runtime_frames: Annotated[int, Field(ge=1)]
    shots: Annotated[list[Shot], Field(min_length=1)]


class Episode(StrictModel):
    kind: Literal["episode"]
    episode_id: Id
    version: Version
    title: Annotated[str, Field(min_length=1)]
    fps: Annotated[int, Field(ge=1, le=60)]
    assets: AssetLibrary
    scenes: Annotated[list[Scene], Field(min_length=1)]

    @model_validator(mode="after")
    def cross_checks(self) -> Episode:
        problems = episode_problems(self)
        if problems:
            raise ValueError("; ".join(problems))
        return self


class TimingDelta(StrictModel):
    track_id: Id
    start_delta_frames: int = 0
    end_delta_frames: int = 0


class TimingPatch(StrictModel):
    """A schema-valid timing edit.

    The patch names the tracks it may move and how far the shot duration
    grows. It does not carry pose, camera, or dialogue text changes.
    """

    kind: Literal["timing_patch"]
    patch_id: Id
    target_shot_id: Id
    base_revision: Revision
    reason: Annotated[str, Field(min_length=1)]
    timing: Annotated[list[TimingDelta], Field(min_length=1)]
    extend_shot_frames: int = Field(default=0, ge=0)


def episode_problems(episode: Episode) -> list[str]:
    problems: list[str] = []
    characters = {item.asset_id: item for item in episode.assets.characters}
    rigs = {item.asset_id: item for item in episode.assets.rigs}
    backgrounds = {item.asset_id: item for item in episode.assets.backgrounds}
    props = {item.asset_id: item for item in episode.assets.props}
    problems.extend(_duplicate_ids("character", list(characters), len(episode.assets.characters)))
    problems.extend(_duplicate_ids("rig", list(rigs), len(episode.assets.rigs)))
    problems.extend(_duplicate_ids("background", list(backgrounds), len(episode.assets.backgrounds)))
    problems.extend(_duplicate_ids("prop", list(props), len(episode.assets.props)))

    for character in episode.assets.characters:
        rig = rigs.get(character.rig_id)
        if rig is None or rig.version != character.rig_version or rig.character_id != character.asset_id:
            problems.append(f"{character.asset_id} does not resolve to its rig pin")
        overlap = set(character.extension_poses).intersection(allowed_poses(()))
        if overlap:
            problems.append(f"{character.asset_id} redefines standard poses {sorted(overlap)}")
        overlap_controls = set(character.extension_controllers).intersection(allowed_controllers(()))
        if overlap_controls:
            problems.append(
                f"{character.asset_id} redefines standard controllers {sorted(overlap_controls)}"
            )

    scene_ids: list[str] = []
    for scene in episode.scenes:
        scene_ids.append(scene.scene_id)
        if scene.episode_id != episode.episode_id:
            problems.append(f"{scene.scene_id} is parented to {scene.episode_id}")
        if scene.setting_id not in backgrounds:
            problems.append(f"{scene.scene_id} setting {scene.setting_id} is not in the library")
        problems.extend(_scene_timeline(scene, episode.fps, characters, rigs, backgrounds, props))
    problems.extend(_duplicate_ids("scene", scene_ids, len(scene_ids)))
    return problems


def _scene_timeline(scene, fps, characters, rigs, backgrounds, props) -> list[str]:
    problems: list[str] = []
    shots = sorted(scene.shots, key=lambda shot: (shot.start_frame, shot.shot_id))
    if [shot.shot_id for shot in shots] != [shot.shot_id for shot in scene.shots]:
        problems.append(f"{scene.scene_id} shots must be ordered by start_frame")
    cursor = 0
    timeline_end = 0
    shot_ids: list[str] = []
    for shot in scene.shots:
        shot_ids.append(shot.shot_id)
        if shot.scene_id != scene.scene_id:
            problems.append(f"{shot.shot_id} is parented to {shot.scene_id}")
        if shot.fps != fps:
            problems.append(f"{shot.shot_id} fps {shot.fps} does not match the episode")
        if shot.start_frame < cursor:
            problems.append(f"{shot.shot_id} overlaps the previous shot")
        cursor = shot.start_frame + shot.duration_frames
        timeline_end = max(timeline_end, cursor)
        problems.extend(_shot_assets(shot, scene, characters, rigs, backgrounds, props))
    if timeline_end > scene.target_runtime_frames:
        problems.append(
            f"{scene.scene_id} timeline ends at {timeline_end}, past target {scene.target_runtime_frames}"
        )
    problems.extend(_duplicate_ids("shot", shot_ids, len(shot_ids)))
    return problems


def _shot_assets(shot, scene, characters, rigs, backgrounds, props) -> list[str]:
    problems: list[str] = []
    pinned = {(ref.role, ref.asset_id): ref.version for ref in shot.asset_refs}
    if ("background", scene.setting_id) not in pinned:
        problems.append(f"{shot.shot_id} does not pin background {scene.setting_id}")
    for actor in shot.actors:
        character = characters.get(actor.character_id)
        rig = rigs.get(actor.rig_id)
        if character is None:
            problems.append(f"{actor.actor_id} character {actor.character_id} is not in the library")
            continue
        if rig is None:
            problems.append(f"{actor.actor_id} rig {actor.rig_id} is not in the library")
            continue
        if pinned.get(("character", actor.character_id)) != character.version:
            problems.append(f"{shot.shot_id} character pin for {actor.character_id} does not match")
        if pinned.get(("rig", actor.rig_id)) != rig.version:
            problems.append(f"{shot.shot_id} rig pin for {actor.rig_id} does not match")
        if actor.rig_id != character.rig_id:
            problems.append(f"{actor.actor_id} uses {actor.rig_id}, not {character.rig_id}")
        poses = allowed_poses(character.extension_poses)
        controllers = allowed_controllers(character.extension_controllers)
        for track in shot.action_tracks:
            if track.target_actor_id != actor.actor_id:
                continue
            for key in track.keyframes:
                if key.pose not in poses:
                    problems.append(f"{track.track_id} uses unapproved pose {key.pose}")
            for controller in track.mask:
                if controller not in controllers:
                    problems.append(f"{track.track_id} uses unknown controller {controller}")
    for ref in shot.asset_refs:
        library = {"character": characters, "rig": rigs, "background": backgrounds, "prop": props}[ref.role]
        item = library.get(ref.asset_id)
        if item is None or item.version != ref.version:
            problems.append(f"{shot.shot_id} {ref.role} ref {ref.asset_id}@{ref.version} does not resolve")
    return problems


def _reject_overlapping_dialogue(tracks: list[DialogueTrack]) -> None:
    ordered = sorted(tracks, key=lambda track: track.start_frame)
    for earlier, later in zip(ordered, ordered[1:]):
        if later.start_frame < earlier.end_frame:
            raise ValueError(f"{earlier.track_id} overlaps {later.track_id}")


def _reject_ambiguous_mix(tracks: list[ActionTrack]) -> None:
    for index, left in enumerate(tracks):
        for right in tracks[index + 1 :]:
            if left.target_actor_id != right.target_actor_id or left.priority != right.priority:
                continue
            if left.end_frame <= right.start_frame or right.end_frame <= left.start_frame:
                continue
            if set(left.mask).intersection(right.mask):
                raise ValueError(f"{left.track_id} and {right.track_id} share priority, time, and mask")


def _unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")


def _duplicate_ids(label: str, ids: list[str], count: int) -> list[str]:
    if len(set(ids)) != count:
        return [f"duplicate {label} id"]
    return []
