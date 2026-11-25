# Voice and visemes

A line becomes a waveform, sample-accurate alignment, and a viseme track. The episode stores the take id, the timing, and the visemes. The waveform and the vendor voice id stay outside the IR, on the take record and the voice profile.

A profile is data for one character: `provider` (`fixture` or `elevenlabs`), `provider_voice_id`, a consent note, and an optional pronunciation dictionary. Missing consent is rejected. ElevenLabs is used only when the profile names it and `ELEVENLABS_API_KEY` is set. `fixture` is a deterministic tone for projects that are not calling a vendor.

Before synthesis, the `voice_prep` step asks the model router for an emotion and any extra pronunciations. Claude is first, then Gemini, then Cursor. If none are configured, the line is still dubbed and the emotion is `neutral`.

Visemes are `rest`, `MBP`, `FV`, `TH`, `AA`, `EE`, `OH`, and `L`. A new shape starts at weight 0.45 so the jaw eases in. The preview uses that shape for the mouth and jaw. It does not flap the mouth from volume.

```bash
python3 -m cuervo_voice examples/reference-scene.json examples/sample-series/voices.json \
  -o /tmp/dubbed.json --wav-dir /tmp/takes
```
