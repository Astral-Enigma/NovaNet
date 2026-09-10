"""Reading and writing rows.

One place for every query, so a route asks for what it needs rather than assembling SQL
inline. Nothing here renders anything.
"""

from datetime import datetime, timezone

from config import CREATURE_FIELDS, FIELDS, NUMERIC_FIELDS, TECHNIQUE_FIELDS
from db import get_connection

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def format_stamp(raw):
    """Render a stored ISO timestamp as a short, readable UTC time."""
    try:
        return datetime.fromisoformat(raw).strftime("%b %d %H:%M")
    except (TypeError, ValueError):
        return str(raw)


def read_characters():
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT characters.*, players.name AS player_name FROM characters "
            "JOIN players ON characters.player_id = players.id ORDER BY characters.id"
        )]
    finally:
        conn.close()


def read_character(id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT characters.*, players.name AS player_name FROM characters "
            "JOIN players ON characters.player_id = players.id WHERE characters.id = ?",
            (id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def read_characters_for_player(player_id):
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM characters WHERE player_id = ? ORDER BY id", (player_id,)
        )]
    finally:
        conn.close()


def read_techniques_for_character(character_id):
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM techniques WHERE character_id = ? ORDER BY id", (character_id,)
        )]
    finally:
        conn.close()


def read_technique(id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM techniques WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def to_typed_technique_values(form):
    values = []
    for f in TECHNIQUE_FIELDS:
        raw = form.get(f, "")
        if f == "toll":
            try:
                values.append(int(raw))
            except (TypeError, ValueError):
                values.append(0)
        else:
            values.append(raw)
    return values


def read_creatures():
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM creatures ORDER BY id")]
    finally:
        conn.close()


def read_creature(id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM creatures WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def to_typed_creature_values(form):
    values = []
    for f in CREATURE_FIELDS:
        raw = form.get(f, "")
        if f == "default_threat_level":
            try:
                values.append(int(raw))
            except (TypeError, ValueError):
                values.append(1)
        else:
            values.append(raw)
    return values


def read_rooms():
    conn = get_connection()
    try:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT rooms.*, players.name AS creator_name,
                       (SELECT COUNT(*) FROM room_members WHERE room_id = rooms.id) AS member_count
                FROM rooms JOIN players ON players.id = rooms.created_by
                ORDER BY rooms.id DESC
                """
            )
        ]
    finally:
        conn.close()


def read_room(id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM rooms WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def read_room_members(room_id):
    conn = get_connection()
    try:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT characters.*, room_members.joined_at, players.name AS player_name
                FROM room_members
                JOIN characters ON characters.id = room_members.character_id
                JOIN players ON players.id = characters.player_id
                WHERE room_members.room_id = ?
                ORDER BY room_members.id
                """,
                (room_id,),
            )
        ]
    finally:
        conn.close()


def read_room_messages(room_id, limit=200):
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT room_messages.*,
                   characters.name AS character_name,
                   room_enemies.name AS enemy_name
            FROM room_messages
            LEFT JOIN characters ON characters.id = room_messages.character_id
            LEFT JOIN room_enemies ON room_enemies.id = room_messages.enemy_id
            WHERE room_messages.room_id = ?
            ORDER BY room_messages.id DESC LIMIT ?
            """,
            (room_id, limit),
        )
        return [dict(row) for row in rows][::-1]
    finally:
        conn.close()


def post_room_message(room_id, character_id, kind, body, enemy_id=None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO room_messages (room_id, character_id, enemy_id, kind, body, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (room_id, character_id, enemy_id, kind, body, utc_now()),
        )
        conn.commit()
    finally:
        conn.close()


def read_room_enemies(room_id, include_dismissed=False):
    clause = "" if include_dismissed else " AND dismissed_at IS NULL"
    conn = get_connection()
    try:
        return [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM room_enemies WHERE room_id = ?{clause} ORDER BY id", (room_id,)
            )
        ]
    finally:
        conn.close()


def read_room_enemy(id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM room_enemies WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def character_in_room(room_id, player_id):
    """Return the caller's character in this room, or None if they have not joined."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT characters.* FROM room_members
            JOIN characters ON characters.id = room_members.character_id
            WHERE room_members.room_id = ? AND characters.player_id = ?
            """,
            (room_id, player_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def read_players():
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM players ORDER BY id")]
    finally:
        conn.close()


def read_player(id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM players WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_current_player(request):
    player_id = request.session.get("player_id")
    return read_player(player_id) if player_id else None
