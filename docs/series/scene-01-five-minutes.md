# Scene 01 — Five Minutes

32 seconds at 24 fps (768 frames). Dialogue-heavy. Two people, one room. The authoritative timing is `examples/reference-scene.json`. This page is the script those tracks transcribe.

INT. NIA'S LIVING ROOM — EVENING

Nia is on the left cushion, laptop closed beside her. Cole drops onto the right cushion. The television is off.

COLE
You said five minutes.

NIA
I said five minutes of quiet. You used four of them finding the remote.

COLE
It's under you.

Nia looks at him and holds.

NIA
Then we watch nothing.

COLE
That's the plan I had before I sat down.

They both look at the dark television.

## Shot plan

| Shot | Frames | Duration | Preset | What the audience sees |
| --- | --- | --- | --- | --- |
| `sh_establish` | 0–96 | 4.0s | wide | Both seated. Nia blinks once. |
| `sh_two_shot` | 96–408 | 13.0s | two-shot | Three lines. Cole shrugs, then points. Nia goes deadpan. |
| `sh_reaction` | 408–552 | 6.0s | close-up | "Then we watch nothing." The `react` pose holds to the cut. |
| `sh_button` | 552–768 | 9.0s | two-shot | Cole's last line, then both look at the television. |

Frame numbers on a shot's tracks are local to that shot. `examples/hold-reaction-12.patch.json` lengthens only `tr_nia_react` and this shot by 12 frames, and slides the button later to match.
