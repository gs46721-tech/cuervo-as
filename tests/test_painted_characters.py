"""Characters painted by an image model, cut into parts, and animated."""

from io import BytesIO

import pytest
from PIL import Image

from cuervo_runtime.draw import render_png
from cuervo_world import World, WorldError
from cuervo_world.cutout import CutError, cut_character
from cuervo_world.design import CharacterDesign
from cuervo_world.imagegen import character_prompt
from cuervo_pipeline.produce import produce
from tests.standin import painted_character
from tests.test_production import SCRIPT, _designed_kit

SKIN, HAIR, TOP, BOTTOM = (150, 95, 65), (30, 22, 20), (205, 120, 60), (47, 53, 66)


def _picture(**pose) -> Image.Image:
    return Image.open(BytesIO(painted_character(SKIN, HAIR, TOP, BOTTOM, **pose))).convert("RGB")


class Painter:
    name = "gemini"
    default_model = "stand-in"

    def __init__(self, **pose):
        self.pose = pose
        self.prompts: list[str] = []

    def available(self) -> bool:
        return True

    def paint(self, prompt: str, model: str | None = None) -> bytes:
        self.prompts.append(prompt)
        return painted_character(SKIN, HAIR, TOP, BOTTOM, **self.pose)


def test_a_painted_figure_is_cut_at_the_joints_into_a_rig():
    parts, rig = cut_character(_picture(), CharacterDesign(height=1.0))
    assert {"torso", "head", "upper_arm", "forearm", "thigh", "shin", "eye_patch", "eye_closed", "mouth_patch", "mouth_AA"} <= set(parts)
    assert rig["face_mode"] == "painted"
    # The whole figure is the house height, so painted and house characters stand eye to eye.
    head, torso, thigh, shin = (rig["parts"][name]["size"][1] for name in ("head", "torso", "thigh", "shin"))
    assert 270 < head + torso + thigh + shin < 330
    # Joints are where a body has them: neck above the hips, shoulders out and up, knees below the hips.
    assert rig["neck"][1] < -60 and abs(rig["neck"][0]) < 3
    assert rig["shoulder"][0] > 20 and rig["shoulder"][1] < -40
    assert rig["hip"][0] > 5 and rig["knee"][1] > 20 and rig["elbow"][1] > 15
    assert rig["face"]["eye_l"][0] < 0 < rig["face"]["eye_r"][0] and rig["face"]["mouth"][1] > rig["face"]["eye_l"][1]
    # The background is gone and the colors are the painter's, not tinted by it.
    torso_image = parts["torso"]
    assert torso_image.getpixel((0, 0))[3] == 0
    assert torso_image.getpixel((torso_image.width // 2, torso_image.height // 3))[:3] == TOP
    # The patch that hides the painted mouth is the character's own skin.
    patch = parts["mouth_patch"]
    assert patch.getpixel((patch.width // 2, patch.height // 2))[:3] == SKIN


def test_a_pose_that_cannot_be_cut_says_what_to_ask_for():
    with pytest.raises(CutError, match="arms touch the body"):
        cut_character(_picture(arms_apart=False), CharacterDesign())
    with pytest.raises(CutError, match="legs are together"):
        cut_character(_picture(legs_apart=False), CharacterDesign())
    with pytest.raises(CutError, match="no character"):
        cut_character(Image.new("RGB", (800, 1200), (20, 235, 40)), CharacterDesign())


def test_the_prompt_asks_for_the_pose_the_cutter_needs():
    prompt = character_prompt("Ada", CharacterDesign(description="Careful and dry.", glasses=True, long_sleeves=False), ["A workshop comedy."])
    for phrase in ("facing the viewer", "held clearly away from the body", "legs are straight and set apart", "plain solid bright", "The character: Ada.", "Careful and dry.", "short sleeves", "Wears glasses.", "A workshop comedy."):
        assert phrase in prompt


def test_a_painted_look_is_offered_beside_the_house_style_and_animates_when_picked(tmp_path):
    kit = _designed_kit()
    painter = Painter()
    result = produce(SCRIPT, kit, tmp_path, router=None, through="animation", painters=[("gemini", "")], log=lambda _line: None)
    # Nothing was painted there: the default engines have no key. Build a world with the stand-in painter instead.
    world = World(tmp_path / "painted")
    world.build(kit, painters=[("gemini", "")], engines={"gemini": painter})
    assert any("The character: Ada." in prompt for prompt in painter.prompts)
    entry = world.entry("char_ada")
    assert [item["by"] for item in entry["candidates"]] == ["house style", "gemini stand-in"]
    # The house style stays in use until a person picks the painted look.
    assert entry["chosen"] == 0 and world.character("char_ada", "1.0.0").rig.get("face_mode") is None
    assert world.candidate_path("char_ada", 1).name == "sheet.png"
    assert (tmp_path / "painted" / "characters" / "char_ada" / "1.0.0" / "painted-1" / "reference.png").is_file()

    episode = result.episode
    shot = next(shot for scene in episode.scenes for shot in scene.shots if shot.dialogue_tracks and shot.dialogue_tracks[0].speaker_actor_id == "act_ada")
    line = shot.dialogue_tracks[0]
    before = render_png(episode, shot, line.start_frame + 2, kit.poses, world=world)
    stamp = world.stamp(["char_ada"])
    world.choose("char_ada", 1)
    assert world.character("char_ada", "1.0.0").rig["face_mode"] == "painted"
    assert world.entry("char_ada")["source"] == "gemini stand-in" and world.stamp(["char_ada"]) != stamp
    speaking = render_png(episode, shot, line.start_frame + 2, kit.poses, world=world)
    assert speaking != before
    colors = dict((color, count) for count, color in Image.open(BytesIO(speaking)).convert("RGB").getcolors(1_000_000))
    assert colors.get(TOP, 0) > 200
    # Lip sync still works on a painted face: the mouth changes while the line is spoken.
    frames = {render_png(episode, shot, frame, kit.poses, world=world) for frame in range(line.start_frame, line.end_frame)}
    assert len(frames) > 2

    # An approved look is frozen, and the house style can be picked again after reopening.
    world.approve("char_ada")
    with pytest.raises(WorldError, match="Reopen"):
        world.choose("char_ada", 0)
    world.approve("char_ada", False)
    world.choose("char_ada", 0)
    assert render_png(episode, shot, line.start_frame + 2, kit.poses, world=world) == before


def test_a_picture_that_cannot_be_cut_is_reported_and_not_offered(tmp_path):
    logs: list[str] = []
    world = World(tmp_path)
    world.build(_designed_kit(), painters=[("gemini", "")], engines={"gemini": Painter(arms_apart=False)}, log=logs.append)
    assert world.entry("char_ada")["candidates"] == [{"file": "house", "by": "house style"}]
    assert any("Ada: the picture from gemini was not used. The arms touch the body" in line for line in logs)
