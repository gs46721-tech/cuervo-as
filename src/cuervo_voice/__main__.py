import argparse
import json
from pathlib import Path

from cuervo_ir.credentials import Credentials
from cuervo_ir.models import Episode
from cuervo_voice.dub import VoiceProfile, dub_episode


def main() -> None:
    parser = argparse.ArgumentParser(description="Dub every line in an episode from voice profiles.")
    parser.add_argument("episode", type=Path)
    parser.add_argument("profiles", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--wav-dir", type=Path, required=True)
    args = parser.parse_args()
    Credentials()
    episode = Episode.model_validate(json.loads(args.episode.read_text(encoding="utf-8")))
    profiles = [VoiceProfile.model_validate(item) for item in json.loads(args.profiles.read_text(encoding="utf-8"))]
    dubbed, takes = dub_episode(episode, profiles)
    args.output.write_text(dubbed.model_dump_json(indent=2) + "\n", encoding="utf-8")
    args.wav_dir.mkdir(parents=True, exist_ok=True)
    for take in takes:
        (args.wav_dir / f"{take.take_id}.wav").write_bytes(take.wav)


if __name__ == "__main__":
    main()
