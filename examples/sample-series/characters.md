# Sample characters

Sample data only. The engine accepts any character ids that follow the rig contract.

Two characters. Both are rigged to `cuervo.rig.v0`. Extensions are listed in the episode library and here.

## Nia Adeyemi

`char_nia`, rig `rig_nia` version 1.0.0.

She owns the apartment. She talks in finished sentences and holds still when she is annoyed. Her extra pose is `deadpan`: level brows, a small mouth, eyes that do not widen.

On the couch she is the left figure, three-quarter facing right, stage x = -180 px, y = 40 px, depth 2.

## Cole Park

`char_cole`, rig `rig_cole` version 1.0.0.

He is visiting. He talks with his hands and fills silence. His extra pose is `fidget`: a small repeated hand movement while the body stays in `sit`. The reference scene does not use it yet. The contract allows it so a later take can, without adding a controller.

On the couch he is the right figure, three-quarter facing left, stage x = 180 px, y = 40 px, depth 2.

## Identity in the scene

Every shot in this sample instances the same actor ids (`act_nia`, `act_cole`), the same rig instances, the same stage transforms, and the same facing. Cuts are camera changes. The sample fixture test checks that this particular episode does not move them.
