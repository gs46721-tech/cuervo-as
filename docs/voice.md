# Voice and lip sync

A line becomes a take: a waveform at the length the line takes to say, and an alignment that says which sound falls on which sample. The episode stores the take id, the timing, and the visemes. The waveform and the vendor voice id stay outside the IR, in the takes folder and the series kit.

## Voices

A voice belongs to a character in the series kit:

```json
"voice": {
  "provider": "elevenlabs",
  "provider_voice_id": "your-voice-id",
  "consent": "Licensed from the performer on 2026-01-10.",
  "model_id": "eleven_multilingual_v2",
  "settings": {"stability": 0.45, "similarity_boost": 0.8, "speed": 1.0},
  "pronunciation": {"papa": "AA"}
}
```

`provider` is `elevenlabs` or `fixture`. A consent note is required. `fixture` is a tone with the length and timing of the line, for work that should not call a vendor.

## ElevenLabs

Connect the account in the editor under **Accounts and keys**, or set `ELEVENLABS_API_KEY`. Testing the key there lists the voice ids on the account.

Each line is one request to `POST /v1/text-to-speech/{voice_id}/with-timestamps`. The reply carries the audio and the start and end time of every character. `ELEVENLABS_MODEL` sets the default model and `ELEVENLABS_PCM_RATE` the requested rate (24000 by default). Audio is resampled to 48 kHz.

A take is cached by its text, voice, model, and settings. A second run does not pay for a line that has not changed.

This adapter is tested against the documented response shape. It has not been run against a live ElevenLabs account from this repo.

## Lip sync

The alignment turns measured character times into mouth shapes: `rest`, `MBP`, `FV`, `TH`, `AA`, `EE`, `OH`, and `L`.

- A vowel or a lip sound takes its own shape. `th` is one shape. A final silent `e` holds the shape before it.
- Other consonants use `L`, a slightly open mouth, so the mouth does not snap shut inside a word.
- A measured silence of 0.12 seconds or more closes the mouth.
- A word in the pronunciation dictionary takes one shape for its whole length.
- A new shape starts at weight 0.45 so the jaw eases in. The mouth never follows volume.

A take is `measured` when the vendor timed the characters. It is `estimated` when the letters were spread evenly across the audio, and the polish stage flags those lines.

In the editor, a project opened with `--takes` plays the voices. While sound plays it is the clock, so the picture follows the words.

## Dubbing an episode that is already timed

`dub_episode` fits each take into the frames a line already has. Use the pipeline instead when the animation should follow the performance.

```bash
python3 -m cuervo_voice examples/reference-scene.json examples/sample-series/voices.json \
  -o /tmp/dubbed.json --wav-dir /tmp/takes
```
