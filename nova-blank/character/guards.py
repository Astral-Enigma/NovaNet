"""Who is allowed to do what.

Each of these answers a question a route asks before acting: is somebody logged in, do
they own this character, are they the Headmaster, have they joined this room.
"""

import os
import secrets

from fastapi import HTTPException
from fastapi.responses import RedirectResponse

from queries import character_in_room, get_current_player, read_room

def require_hm_login(request):
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    if not current_player["is_hm"]:
        raise HTTPException(status_code=403, detail="HM access required")
    return None


def export_token_is_valid(supplied):
    """Allow the backup script in without a browser session.

    Only works when NOVANET_EXPORT_TOKEN is configured, so an unset variable can never be
    matched by an empty query parameter.
    """
    expected = os.environ.get("NOVANET_EXPORT_TOKEN", "")
    if not expected or not supplied:
        return False
    return secrets.compare_digest(str(supplied), expected)


def require_owner_or_hm(current_player, character):
    if current_player["id"] != character["player_id"] and not current_player["is_hm"]:
        raise HTTPException(status_code=403, detail="Not permitted to modify this character")


def can_edit_character(request, character):
    current_player = get_current_player(request)
    return current_player is not None and (
        current_player["id"] == character["player_id"] or current_player["is_hm"]
    )


def can_close_room(room, current_player):
    """Only whoever opened the room, or an HM, may close or reopen it."""
    if current_player is None:
        return False
    return room["created_by"] == current_player["id"] or bool(current_player["is_hm"])


def require_room_membership(id, request, allow_closed=False):
    """Return (room, character) for a caller allowed to act in this room."""
    room = read_room(id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    if room["closed_at"] and not allow_closed:
        raise HTTPException(status_code=403, detail="This room is closed.")
    current_player = get_current_player(request)
    if current_player is None:
        return None, None
    character = character_in_room(id, current_player["id"])
    if character is None:
        raise HTTPException(status_code=403, detail="Join this room as a character first")
    return room, character


def require_room_hm(id, request):
    """Return (room, player) for an HM acting in an open room.

    Running enemies is the HM's job rather than a character's, so this deliberately does
    not require them to have joined the room as one.
    """
    room = read_room(id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    current_player = get_current_player(request)
    if current_player is None:
        return None, None
    if not current_player["is_hm"]:
        raise HTTPException(status_code=403, detail="Only the Headmaster can run enemies.")
    if room["closed_at"]:
        raise HTTPException(status_code=403, detail="This room is closed.")
    return room, current_player
