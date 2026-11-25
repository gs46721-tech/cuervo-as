"""Natural-language shot edits as typed patches."""

from cuervo_edit.edits import EditError, EditPatch, affected, apply_edit, preview_frame
from cuervo_edit.propose import propose_edit

__all__ = [
    "EditError",
    "EditPatch",
    "affected",
    "apply_edit",
    "preview_frame",
    "propose_edit",
]
