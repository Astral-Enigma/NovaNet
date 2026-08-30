# Character creator FastAPI app.
# Allows creating characters with any fields defined in FIELDS, saved to a SQLite database.
# Install dependencies on Ubuntu:
#   sudo apt update && sudo apt install -y python3-pip
#   pip3 install fastapi uvicorn python-multipart
# Run:
#   uv run --with fastapi --with uvicorn --with python-multipart --with itsdangerous python3 main.py

import csv
import json
import math
import os
import random
import secrets
import sqlite3
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

# Hosts like Render give each deploy a fresh, empty filesystem, so anything written next to
# this file is wiped every time the app ships. NOVANET_DATA_DIR points the database and the
# session secret at a persistent disk instead; it defaults to alongside the code so local
# development is unchanged.
DATA_DIR = Path(os.environ.get("NOVANET_DATA_DIR", Path(__file__).parent))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SECRET_KEY_FILE = DATA_DIR / "session_secret.txt"


def load_session_secret():
    # A freshly generated secret on every start would log every user out on restart, so
    # prefer the environment and fall back to a secret persisted next to the database.
    from_env = os.environ.get("NOVANET_SECRET_KEY")
    if from_env:
        return from_env
    if SECRET_KEY_FILE.exists():
        stored = SECRET_KEY_FILE.read_text().strip()
        if stored:
            return stored
    generated = secrets.token_hex(32)
    SECRET_KEY_FILE.write_text(generated)
    SECRET_KEY_FILE.chmod(0o600)
    return generated


app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=load_session_secret())

CSV_FILE = Path(__file__).parent / "characters.csv"
# The complete backup. characters.csv stays as a legacy fallback for databases seeded
# before snapshots existed.
SNAPSHOT_FILE = Path(__file__).parent / "seed.json"
DB_FILE = DATA_DIR / "characters.db"
HOME_FILE = Path(__file__).parent / "home.html"
CHARACTER_NEW_FILE = Path(__file__).parent / "character_new.html"
LIST_FILE = Path(__file__).parent / "characters.html"
EDIT_FILE = Path(__file__).parent / "edit.html"
PLAYERS_FILE = Path(__file__).parent / "players.html"
PLAYER_PROFILE_FILE = Path(__file__).parent / "player_profile.html"
LOGIN_FILE = Path(__file__).parent / "login.html"
TECHNIQUES_FILE = Path(__file__).parent / "techniques.html"
TECHNIQUE_NEW_FILE = Path(__file__).parent / "technique_new.html"
TECHNIQUE_EDIT_FILE = Path(__file__).parent / "technique_edit.html"
ENEMIES_FILE = Path(__file__).parent / "enemies.html"
ENEMY_NEW_FILE = Path(__file__).parent / "enemy_new.html"
ENEMY_EDIT_FILE = Path(__file__).parent / "enemy_edit.html"
ENEMY_GENERATED_FILE = Path(__file__).parent / "enemy_generated.html"
PLAY_FILE = Path(__file__).parent / "play.html"
ROOM_FILE = Path(__file__).parent / "room.html"
ERROR_FILE = Path(__file__).parent / "error.html"
STYLE_FILE = Path(__file__).parent / "style.css"
FIELDS = ["name", "age", "rank", "clan", "house", "trait", "trauma", "pneuma", "deftness", "handling", "tenacity", "wit", "perception", "composure", "pluck", "potential",]
NUMERIC_FIELDS = ["age", "trauma", "pneuma", "deftness", "handling", "tenacity", "wit", "perception", "composure", "pluck", "potential"]
TECHNIQUE_FIELDS = ["name", "description", "toll", "type", "category", "effect", "burst", "duration"]
CREATURE_FIELDS = ["name", "description", "habitat", "main_skill", "default_threat_level", "talent_name", "talent_effect", "drops"]
SKILLS = ["Deftness", "Handling", "Tenacity", "Wit", "Perception", "Composure"]
HABITATS = ["Land Dwelling", "Sky-Faring", "Sea-Faring", "Celestial", "Damned"]
# Master rank rolls 6d6; techniques, weapons, and Flash Dice stack on top of that, so this
# cap is far above any legitimate Nova roll while keeping an unbounded pool from exhausting
# memory and taking the whole server down.
MAX_DICE = 100
RANK_DICE = {
    "Novice": (1, 1),
    "Rookie": (2, 1),
    "Genius": (3, 2),
    "Expert": (4, 3),
    "Veteran": (5, 4),
    "Master": (6, 5),
}
# Creature Threat Levels are ranks by another name, so 1..6 indexes straight into this.
RANK_ORDER = list(RANK_DICE)


def get_connection():
    # busy_timeout and synchronous are per-connection, so they belong here. journal_mode is
    # a property of the database file itself and is set once in enable_wal(); re-issuing it
    # per request costs a lock acquisition on every single call.
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def enable_wal():
    """Switch the database to write-ahead logging, once, at startup.

    Several people share a room and every open page polls the log, so reads and writes
    overlap constantly. Under the default rollback journal a writer takes an exclusive lock
    that blocks readers outright. WAL lets readers carry on while one writer works, which is
    exactly the shape of this traffic.
    """
    conn = sqlite3.connect(DB_FILE, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
    finally:
        conn.close()


def init_db():
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                is_hm INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER NOT NULL REFERENCES players(id),
                name TEXT NOT NULL,
                age INTEGER NOT NULL,
                rank TEXT NOT NULL,
                clan TEXT NOT NULL,
                house TEXT NOT NULL,
                trait TEXT NOT NULL,
                trauma INTEGER NOT NULL,
                pneuma INTEGER NOT NULL,
                deftness INTEGER NOT NULL,
                handling INTEGER NOT NULL,
                tenacity INTEGER NOT NULL,
                wit INTEGER NOT NULL,
                perception INTEGER NOT NULL,
                composure INTEGER NOT NULL,
                pluck INTEGER NOT NULL DEFAULT 0,
                potential INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS techniques (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL REFERENCES characters(id),
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                toll INTEGER NOT NULL,
                type TEXT NOT NULL,
                category TEXT NOT NULL,
                effect TEXT NOT NULL,
                burst TEXT NOT NULL DEFAULT '',
                duration TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS creatures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                habitat TEXT NOT NULL,
                main_skill TEXT NOT NULL,
                default_threat_level INTEGER NOT NULL,
                talent_name TEXT NOT NULL,
                talent_effect TEXT NOT NULL,
                drops TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_by INTEGER NOT NULL REFERENCES players(id),
                created_at TEXT NOT NULL,
                closed_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS room_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL REFERENCES rooms(id),
                character_id INTEGER NOT NULL REFERENCES characters(id),
                joined_at TEXT NOT NULL,
                UNIQUE (room_id, character_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS room_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL REFERENCES rooms(id),
                character_id INTEGER REFERENCES characters(id),
                enemy_id INTEGER REFERENCES room_enemies(id),
                kind TEXT NOT NULL DEFAULT 'text',
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS room_enemies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL REFERENCES rooms(id),
                creature_id INTEGER REFERENCES creatures(id),
                name TEXT NOT NULL,
                threat_level INTEGER NOT NULL,
                stats TEXT NOT NULL,
                talent_name TEXT NOT NULL DEFAULT '',
                talent_effect TEXT NOT NULL DEFAULT '',
                talent_uses INTEGER NOT NULL DEFAULT 0,
                talent_cooldown INTEGER NOT NULL DEFAULT 0,
                dismissed_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        migrate_player_id_if_needed(conn)
        migrate_is_hm_if_needed(conn)
        migrate_room_closed_at_if_needed(conn)
        migrate_message_enemy_id_if_needed(conn)
    finally:
        conn.close()


def migrate_player_id_if_needed(conn):
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(characters)")]
    if "player_id" in columns:
        return
    conn.execute("ALTER TABLE characters ADD COLUMN player_id INTEGER")
    unassigned_id = get_or_create_unassigned_player(conn)
    conn.execute("UPDATE characters SET player_id = ? WHERE player_id IS NULL", (unassigned_id,))
    conn.commit()


def migrate_is_hm_if_needed(conn):
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(players)")]
    if "is_hm" in columns:
        return
    conn.execute("ALTER TABLE players ADD COLUMN is_hm INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def migrate_room_closed_at_if_needed(conn):
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(rooms)")]
    if "closed_at" in columns:
        return
    conn.execute("ALTER TABLE rooms ADD COLUMN closed_at TEXT")
    conn.commit()


def migrate_message_enemy_id_if_needed(conn):
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(room_messages)")]
    if "enemy_id" in columns:
        return
    conn.execute("ALTER TABLE room_messages ADD COLUMN enemy_id INTEGER")
    conn.commit()


def get_or_create_unassigned_player(conn):
    row = conn.execute("SELECT id FROM players WHERE name = 'Unassigned'").fetchone()
    if row:
        return row["id"]
    cursor = conn.execute("INSERT INTO players (name) VALUES ('Unassigned')")
    conn.commit()
    return cursor.lastrowid


# The seed CSV carries the owning player alongside each character so that ownership and HM
# status survive a reseed. Older files without these columns still load; their characters
# fall back to the Unassigned player.
CSV_COLUMNS = ["player", "player_is_hm"] + FIELDS


def migrate_csv_if_needed():
    if not CSV_FILE.exists():
        return
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0]
        if count > 0:
            return
        with open(CSV_FILE, newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return
        player_ids = {}
        for row in rows:
            player_name = (row.get("player") or "").strip()
            if not player_name:
                player_id = get_or_create_unassigned_player(conn)
            elif player_name in player_ids:
                player_id = player_ids[player_name]
            else:
                existing = conn.execute(
                    "SELECT id FROM players WHERE name = ?", (player_name,)
                ).fetchone()
                if existing:
                    player_id = existing["id"]
                else:
                    is_hm = 1 if str(row.get("player_is_hm", "")).strip() in ("1", "true", "True") else 0
                    player_id = conn.execute(
                        "INSERT INTO players (name, is_hm) VALUES (?, ?)", (player_name, is_hm)
                    ).lastrowid
                player_ids[player_name] = player_id
            values = to_typed_values(row)
            conn.execute(
                f"INSERT INTO characters (player_id, {', '.join(FIELDS)}) "
                f"VALUES (?, {', '.join('?' for _ in FIELDS)})",
                [player_id] + values,
            )
        conn.commit()
    finally:
        conn.close()


# The Creature Catalog is published reference material rather than anything a table
# creates, so it ships with the app. Seeding it here means enemy generation still works
# after a deploy wipes the database, which is not true of anything only stored in SQLite.
# Threat levels are the Catalog's own; main skills must be one of SKILLS for the stat
# generator, so creatures the Catalog gives a conditional skill get their primary here and
# the condition noted in the description.
CATALOG_SEED = [
    # Land Dwelling
    ("Minotaur", "Lives deep underground or in dense forest, manipulating the surrounding area with Pneuma to build mazes it hunts in. Intelligence comparable to a child.",
     "Land Dwelling", "Tenacity", 1, "Maze Master",
     "Passively gains +x to all rolls where x is the number of opponents. Can activate to vanish into the environment, triggering a contested Deftness roll; on success opponents become Rattled and it becomes Obscured until successfully attacked.", "Broken Horn"),
    ("Gorgon", "A person-sized serpent as old as the Clans, dwelling in deep caves and quarries. Its stone diet lets its skin take on enhanced properties of the rock it eats.",
     "Land Dwelling", "Deftness", 2, "Terra Toxin",
     "A two turn attack: coils around the target to Bind it, then injects a hardening venom that solidifies over 3 rounds, killing them. Resistible with strong enough Pneuma or medical supplies.", "Gorgon's Eye"),
    ("Alkalym", "A naturally occurring defence system for caves of compressed Pneumatic energy called Void Shards. Its strength scales with the concentration of shards it guards.",
     "Land Dwelling", "Composure", 4, "Bedrock Beam",
     "Charges for a turn, then fires a Pneumatic beam laced with Terra Toxin that can hit multiple targets. If damage exceeds the target's Pluck they begin to solidify over 3 turns, killing them.", "Void Fragment"),
    ("Chimera", "A grotesque amalgamation of gorgon, takdyl and siren. The siren head lures prey, the gorgon tail petrifies it, and the takdyl torso makes it fast and durable.",
     "Land Dwelling", "Deftness", 5, "Borrowed Talents",
     "Gains 2 Talents from either the Gorgon, Takdyl or Siren.", "Petrified Egg"),
    # Sky-Faring
    ("Mechanicrow", "A Forged-built hybrid species, made to hold the ecosystem of Heirloom Island together after The Blue Scream drove its avian life toward extinction.",
     "Sky-Faring", "Perception", 1, "None", "This creature has no Talent.", "Iron Feather"),
    ("Harpy", "A scavenger evolved by feeding on the Pneuma-soaked corpses of the Battle of Canid Grace. Shifts between beast and humanoid shape at will.",
     "Sky-Faring", "Deftness", 3, "Organic Acceleration",
     "Takes the shape of whatever it last consumed Pneuma from. If it attacks a player it gains access to their Trait for xd6 rounds where x is its Threat Level. Main skill becomes Tenacity when unable to fly.", "Wicked Talon"),
    ("Takdyl", "Harpies that fed on other harpies in desperation. Reptilian and avian both, with two sets of dragon-like wings and extra mouths that ingest prey and expel toxins.",
     "Sky-Faring", "Tenacity", 4, "Rallied Expulsion",
     "Spends a Support action vomiting out impurities, removing x status effects and granting immunity to them for x rounds where x is its Threat Level. Anything touching the expelled fluid gains the effects instead. Main skill becomes Deftness while airborne.", "Noxious Gland"),
    ("Wyvern", "Takdyls that fed on their own kind, roughly triple the size, with wings and eyes numbering as many as it has consumed. Can manifest mouths anywhere on its body.",
     "Sky-Faring", "Tenacity", 5, "True Organic Acceleration",
     "On entering combat its main skill becomes the type and value of the opponent's lowest skill, and re-targets as opponents leave. Can activate to raise that skill by xd6 where x is its Threat Level.", "Oculus Scale"),
    # Sea-Faring
    ("Kelpie", "The merging of a drowned soul and a drowned animal. Generally non-aggressive, capable of telepathic speech and of shaping water into a humanoid form while on land.",
     "Sea-Faring", "Composure", 1, "Shape of Water",
     "On taking lethal damage it shifts to a liquid state instead and gains +x to movement. Triggers x times where x is its Threat Level. Main skill becomes Deftness in water.", "Chipped Hoof"),
    ("Siren", "A soul drowned maliciously and reincarnated in rage. Sees the Color of the Core and hunts those with ill intent by singing them to sleep.",
     "Sea-Faring", "Wit", 3, "Song of Serenity",
     "Sings, rolling 1d20 + Wit. Anyone whose Pluck is exceeded becomes Bound and hallucinates their heart's desire, taking xd6 Pneumatic damage at the end of their turn where x is its Threat Level. Reaching zero Pneuma this way kills the target.", "Withered Tongue"),
    ("Kraken", "Titans cast out of the celestial realm for their destructive nature. Adapts in both personality and physicality to the waters it inhabits.",
     "Sea-Faring", "Wit", 5, "Refractive Skin",
     "Passively refracts elemental energy: against a Pneumatic or Trait attack, roll xd6 where x is its Threat Level and subtract that from the damage. Can activate to blend in via a contested Wit check, becoming Obscured until successfully damaged.", "Scarred Mandible"),
    # Celestial
    ("Phoenix", "One of the original Celestial Beasts, formed from the energy lost each time a target falls to the Pyre Trait. Killing one only scatters it into ash and a new egg.",
     "Celestial", "Composure", 6, "Pyre Phasing",
     "Completely immune to Pyre attacks and statuses, transmuting that damage into bonus health and damage on its next attack. Can activate to turn any Trait based attack into Pyre for 1d6 + x rounds where x is its Threat Level.", "Essence Stone"),
    ("Magnus Dragon", "A Titan created as the Phoenix's predator to balance the Celestial ecosystem. Composed almost entirely of Null energy.",
     "Celestial", "Tenacity", 6, "Bite of the Progenitor",
     "Nullifies the Trait of anything it bites for x rounds where x is its Threat Level unless the target passes a contested Composure roll. Anything killed by this bite cannot be resurrected.", "Distortion Fang"),
    # Damned
    ("The Afflicted", "Souls that were people or wildlife before Ashecorps' influence touched them in death. Individually weak, they travel in threes and call for more.",
     "Damned", "Tenacity", 2, "Swarm",
     "Spends a turn calling for help; each consecutive call adds 1d6/2 Afflicted of the same or lower level to the fight.", "Void Essence"),
    ("Fleshspinner", "The failed emergence of an attempted Haunted creation. Formless, it consumes people who resemble its fractured memories and takes on their attributes.",
     "Damned", "Wit", 5, "Skin Shaping",
     "A two turn attack: bites the target, siphoning xd6 Pneuma where x is its Threat Level, then gains x of the target's techniques and raises its main skill by half the target's corresponding skill.", "Rancid Flesh"),
    ("Zeitghast", "Spirits made of the missing parts of history, cursed to wander. They drain the Pneuma of anyone nearby, usually before a fight can begin at all.",
     "Damned", "Composure", 5, "Shadow Siphon",
     "Passively steals xd6 Pneuma from x targets where x is its Threat Level. Can activate to steal xd6 + x maximum Pneuma from one target, disabling the passive for x rounds. Reaching zero Pneuma in this fight kills the target.", "Swath of Void"),
    ("Kah'clth-Kahban", "A Damned Deity under Ashecorps' command, known to mortals as Ban, the Greed God. Sacrificed his own kingdom for a Dominion the size of his throne room, in which he controls gravity.",
     "Damned", "Tenacity", 6, "Wishes on Weighted Shoulder",
     "At the start of combat rolls xd6 where x is its Threat Level; that result is subtracted from the effectiveness of any opponent action involving major movement. Can activate to make an opponent Winded, removing the previous debuff; used on a Winded opponent it Binds them instead, and on a Bound opponent it doubles the next damage they take.", "Relief of Restriction"),
]


def seed_creature_catalog():
    """Load the Catalog's creatures when none exist, leaving an edited catalog alone."""
    conn = get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM creatures").fetchone()[0] > 0:
            return
        conn.executemany(
            f"INSERT INTO creatures ({', '.join(CREATURE_FIELDS)}) "
            f"VALUES ({', '.join('?' for _ in CREATURE_FIELDS)})",
            CATALOG_SEED,
        )
        conn.commit()
    finally:
        conn.close()


# Everything a table creates. characters.csv only ever covered players and characters, so
# techniques, rooms and their logs were lost on every deploy with no way back. Order matters
# on restore: a row's referents are loaded before it.
SNAPSHOT_TABLES = [
    "players", "characters", "techniques", "creatures",
    "rooms", "room_enemies", "room_members", "room_messages",
]
SNAPSHOT_VERSION = 1


def table_columns(conn, table):
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]


def export_snapshot():
    """Write every table to seed.json, the file the app reloads from on an empty database."""
    conn = get_connection()
    try:
        data = {"version": SNAPSHOT_VERSION, "exported_at": utc_now(), "tables": {}}
        for table in SNAPSHOT_TABLES:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            data["tables"][table] = [dict(row) for row in rows]
    finally:
        conn.close()
    payload = json.dumps(data, indent=1, sort_keys=True)
    try:
        SNAPSHOT_FILE.write_text(payload)
    except OSError:
        # A read-only filesystem must not break the app.
        pass
    return payload


def load_snapshot_if_needed():
    """Restore from seed.json when the database is empty.

    Only columns that still exist are restored, so a snapshot taken before a schema change
    keeps loading instead of failing outright. Ids are preserved because techniques, room
    membership and the message log all reference them.
    """
    if not SNAPSHOT_FILE.exists():
        return False
    conn = get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] > 0:
            return False
        try:
            data = json.loads(SNAPSHOT_FILE.read_text())
        except (OSError, ValueError):
            return False
        tables = data.get("tables") or {}
        if not tables.get("players"):
            return False
        for table in SNAPSHOT_TABLES:
            rows = tables.get(table) or []
            if not rows:
                continue
            existing = set(table_columns(conn, table))
            for row in rows:
                columns = [c for c in row if c in existing]
                if not columns:
                    continue
                conn.execute(
                    f"INSERT OR IGNORE INTO {table} ({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' for _ in columns)})",
                    [row[c] for c in columns],
                )
        conn.commit()
        return True
    finally:
        conn.close()


def export_characters_csv():
    """Write every character back to the seed CSV, owning player included.

    On a host with an ephemeral filesystem this file is lost along with the database, so it
    only protects data once it has been downloaded and committed to the repository. Keeping
    it current means the download is always a complete snapshot.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT characters.*, players.name AS player, players.is_hm AS player_is_hm
            FROM characters JOIN players ON players.id = characters.player_id
            ORDER BY characters.id
            """
        ).fetchall()
    finally:
        conn.close()
    try:
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow({c: row[c] for c in CSV_COLUMNS})
    except OSError:
        # A read-only filesystem must not break character editing.
        pass


def to_typed_values(character):
    values = []
    for f in FIELDS:
        raw = character.get(f, "0")
        if f in NUMERIC_FIELDS:
            try:
                values.append(int(raw))
            except (TypeError, ValueError):
                values.append(0)
        else:
            values.append(raw)
    return values


enable_wal()
init_db()
if not load_snapshot_if_needed():
    migrate_csv_if_needed()
seed_creature_catalog()


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


def render_technique_row(t):
    return (
        "<tr>" + "".join(f"<td>{esc(t[f])}</td>" for f in TECHNIQUE_FIELDS) +
        f"<td><a href='/technique/{t['id']}/edit'>Edit</a></td>"
        f"<td><form method='post' action='/technique/{t['id']}/delete' style='display:inline' "
        f"onsubmit=\"return confirm({js_string('Delete ' + str(t['name']) + '?')})\">"
        f"<button type='submit'>Delete</button></form></td></tr>"
    )


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


def render_creature_row(c):
    return (
        "<tr>" + "".join(f"<td>{esc(c[f])}</td>" for f in CREATURE_FIELDS) +
        f"<td><form method='post' action='/enemy/{c['id']}/generate' style='display:inline'>"
        f"<input type='number' name='threat_level' value='{c['default_threat_level']}' min='1' max='6' style='width:3em' />"
        f"<button type='submit'>Generate</button></form></td>"
        f"<td><a href='/enemy/{c['id']}/edit'>Edit</a></td>"
        f"<td><form method='post' action='/enemy/{c['id']}/delete' style='display:inline' "
        f"onsubmit=\"return confirm({js_string('Delete ' + str(c['name']) + '?')})\">"
        f"<button type='submit'>Delete</button></form></td></tr>"
    )


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def format_stamp(raw):
    """Render a stored ISO timestamp as a short, readable UTC time."""
    try:
        return datetime.fromisoformat(raw).strftime("%b %d %H:%M")
    except (TypeError, ValueError):
        return str(raw)


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


def render_room_messages(messages):
    if not messages:
        return "<p class='quotes'>Nothing has happened here yet.</p>"
    out = []
    for m in messages:
        stamp = esc(format_stamp(m["created_at"]))
        who = esc(m["enemy_name"] or m["character_name"] or "Unknown")
        if m["kind"] == "system":
            out.append(f"<p class='log-system'><span class='log-time'>{stamp}</span> {esc(m['body'])}</p>")
        elif m["kind"] == "roll":
            # Roll bodies are built by the server from rendered dice markup, not user input.
            out.append(
                f"<p class='log-roll'><span class='log-time'>{stamp}</span> "
                f"<strong>{who}</strong> {m['body']}</p>"
            )
        else:
            out.append(
                f"<p class='log-text'><span class='log-time'>{stamp}</span> "
                f"<strong>{who}:</strong> {esc(m['body'])}</p>"
            )
    return "".join(out)


def rank_for_threat(level):
    """Rank name for a Threat Level, clamped.

    Spawning clamps to 1-6, but a stored row can arrive from a snapshot or a hand edit, and
    a single bad value should not take down the whole room page with an IndexError.
    """
    try:
        level = int(level)
    except (TypeError, ValueError):
        level = 1
    return RANK_ORDER[max(1, min(len(RANK_ORDER), level)) - 1]


def render_enemy_panel(room_id, enemies, is_hm, is_closed):
    """The enemy field. Everyone sees who is on it; only the HM gets the controls."""
    if not enemies and not is_hm:
        return ""
    rows = []
    for e in enemies:
        try:
            stats = json.loads(e["stats"])
        except (TypeError, ValueError):
            stats = {}
        stat_text = ", ".join(f"{k} {v}" for k, v in stats.items())
        roll_count, keep_count = RANK_DICE[rank_for_threat(e["threat_level"])]
        actions = ""
        if is_hm and not is_closed:
            actions = (
                f"<form method='post' action='/play/room/{room_id}/enemy/{e['id']}/roll'>"
                "<select name='mode'>"
                f"<option value='threat'>Threat ({roll_count}d6 keep {keep_count})</option>"
                "<option value='d20'>1d20</option></select>"
                "<button type='submit'>Roll</button></form>"
                f"<form method='post' action='/play/room/{room_id}/enemy/{e['id']}/dismiss' "
                "onsubmit=\"return confirm('Remove this enemy from the field?')\">"
                "<button type='submit'>Dismiss</button></form>"
            )
        talent = f"{esc(e['talent_name'])}"
        if e["talent_uses"]:
            talent += f" ({e['talent_uses']} uses, {e['talent_cooldown']} round cooldown)"
        rows.append(
            f"<tr><td>{esc(e['name'])}</td>"
            f"<td>{esc(rank_for_threat(e['threat_level']))} ({e['threat_level']})</td>"
            f"<td>{esc(stat_text)}</td><td>{talent}</td><td>{actions}</td></tr>"
        )
    table = (
        "<table><tr><th>Enemy</th><th>Threat</th><th>Skills</th><th>Talent</th><th></th></tr>"
        + "".join(rows) + "</table>"
    ) if rows else "<p class='quotes'>No enemies on the field.</p>"

    spawn = ""
    if is_hm and not is_closed:
        creatures = read_creatures()
        if creatures:
            options = "".join(
                f"<option value='{c['id']}'>{esc(c['name'])} "
                f"({esc(rank_for_threat(c['default_threat_level']))})</option>"
                for c in creatures
            )
            spawn = (
                f"<form method='post' action='/play/room/{room_id}/enemy'>"
                f"<label>Send in: <select name='creature_id' required>{options}</select></label>"
                "<label>Threat level: <input type='number' name='threat_level' min='1' max='6' "
                "value='' placeholder='catalog default' /></label>"
                "<button type='submit'>Generate</button></form>"
            )
        else:
            spawn = ("<p class='quotes'>The Creature Catalog is empty. "
                     "<a href='/enemies' class='section-link'>Add a creature</a> to send one in.</p>")
    return "<h2>Enemies</h2>" + table + spawn


def render_dice_result(all_rolls, keep_count):
    sorted_rolls = sorted(all_rolls, reverse=True)
    kept, dropped = sorted_rolls[:keep_count], sorted_rolls[keep_count:]
    return (
        "".join(f"<span style='font-weight:bold'>{d}</span> " for d in kept) +
        "".join(f"<span style='color:gray;text-decoration:line-through'>{d}</span> " for d in dropped)
    )


def roll_dice(count, sides):
    return [random.randint(1, sides) for _ in range(count)]


def roll_and_keep(roll_count, keep_count, sides=6):
    all_rolls = roll_dice(roll_count, sides)
    kept_sum = sum(sorted(all_rolls, reverse=True)[:keep_count])
    return all_rolls, kept_sum


def generate_creature_stats(creature, threat_level):
    # Creature Catalog: the main skill is (threat level)d6 + threat level. Every other
    # skill starts at a flat 1 at Novice, then gains 1d6 + 1 per rank above Novice.
    ranks_above_novice = threat_level - 1
    stats = {}
    for skill in SKILLS:
        if skill == creature["main_skill"]:
            stats[skill] = sum(roll_dice(threat_level, 6)) + threat_level
        else:
            stats[skill] = 1 + sum(roll_dice(ranks_above_novice, 6)) + ranks_above_novice
    talent_uses = sum(roll_dice(2, 6)) * threat_level
    talent_cooldown = math.ceil(threat_level / 2)
    return stats, talent_uses, talent_cooldown


def require_hm_login(request):
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    if not current_player["is_hm"]:
        raise HTTPException(status_code=403, detail="HM access required")
    return None


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


def render_nav(request):
    current_player = get_current_player(request)
    links = [
        ("Home", "/"),
        ("Create a Character", "/characters/new"),
        ("Characters", "/characters"),
        ("Players", "/players"),
    ]
    if current_player and current_player["is_hm"]:
        links.append(("Enemies", "/enemies"))
    links.append(("Play", "/play"))
    links.append(("Nova News Network", "#"))
    items = "".join(f"<li class='site-section'><a href='{href}' class='section-link'>{label}</a></li>" for label, href in links)
    if current_player:
        role = "HM" if current_player["is_hm"] else "Student"
        auth = (
            f"<li class='site-section'>Logged in as {esc(current_player['name'])} ({role})</li>"
            "<li class='site-section'><form method='post' action='/logout' style='display:inline'>"
            "<button type='submit' class='section-link'>Logout</button></form></li>"
        )
    else:
        auth = "<li class='site-section'><a href='/login' class='section-link'>Login</a></li>"
    return f"<ul class='nav-links'>{items}{auth}</ul>"


def esc(value):
    """Escape a value for interpolation into HTML text or a quoted attribute."""
    return escape("" if value is None else str(value), quote=True)


def js_string(value):
    """Escape a value as a JS string literal safe inside a double-quoted HTML attribute.

    HTML-escaping alone is not enough here: the parser decodes entities inside the
    attribute before the JavaScript is parsed, so an apostrophe would still break out of
    the string. json.dumps produces a properly escaped literal first.
    """
    return escape(json.dumps("" if value is None else str(value)), quote=True)


def render_character_row(c, show_player):
    player_cell = f"<td>{esc(c['player_name'])}</td>" if show_player else ""
    return (
        "<tr>" + player_cell + "".join(f"<td>{esc(c[f])}</td>" for f in FIELDS) +
        f"<td><a href='/character/{c['id']}/techniques'>Techniques</a></td>"
        f"<td><a href='/character/{c['id']}/edit'>Edit</a></td>"
        f"<td><form method='post' action='/character/{c['id']}/delete' style='display:inline' "
        f"onsubmit=\"return confirm({js_string('Delete ' + str(c['name']) + '?')})\">"
        f"<button type='submit'>Delete</button></form></td></tr>"
    )


def compute_derived_fields(character):
    stat_fields = ["deftness", "handling", "tenacity", "wit", "perception", "composure"]
    try:
        total = sum(int(character[f]) for f in stat_fields)
        pluck = math.ceil(total / 2)
        potential = math.ceil(pluck / 2)
    except (KeyError, ValueError, TypeError):
        pluck = potential = 0
    character["pluck"] = str(pluck)
    character["potential"] = str(potential)
    return character


def render_player_options(players, selected_id=None):
    return "".join(
        f"<option value='{p['id']}'{' selected' if p['id'] == selected_id else ''}>{esc(p['name'])}</option>"
        for p in players
    )


def render_error_page(request, status, detail):
    try:
        nav = render_nav(request)
    except Exception:
        # Never let a failure while rendering the nav mask the original error.
        nav = ""
    return (
        ERROR_FILE.read_text()
        .replace("{{ status }}", esc(status))
        .replace("{{ detail }}", esc(detail))
        .replace("{{ nav }}", nav)
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Render errors as a styled page.

    The default handler returns JSON, which a browser in dark mode paints as white text on
    a black background - the "blackscreen saying not found" people were running into.
    """
    titles = {400: "Bad Request", 403: "Not Permitted", 404: "Not Found", 405: "Not Allowed"}
    title = titles.get(exc.status_code, f"Error {exc.status_code}")
    detail = exc.detail if isinstance(exc.detail, str) else "Something went wrong."
    return HTMLResponse(
        content=render_error_page(request, title, detail),
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


def export_token_is_valid(supplied):
    """Allow the backup script in without a browser session.

    Only works when NOVANET_EXPORT_TOKEN is configured, so an unset variable can never be
    matched by an empty query parameter.
    """
    expected = os.environ.get("NOVANET_EXPORT_TOKEN", "")
    if not expected or not supplied:
        return False
    return secrets.compare_digest(str(supplied), expected)


@app.get("/export/characters.csv")
def export_csv(request: Request, token: str = ""):
    if not export_token_is_valid(token) and get_current_player(request) is None:
        return RedirectResponse(url="/login", status_code=303)
    export_characters_csv()
    return Response(
        content=CSV_FILE.read_text() if CSV_FILE.exists() else "",
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=characters.csv"},
    )


@app.get("/export/snapshot.json")
def export_snapshot_route(request: Request, token: str = ""):
    if not export_token_is_valid(token) and get_current_player(request) is None:
        return RedirectResponse(url="/login", status_code=303)
    return Response(
        content=export_snapshot(),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=seed.json"},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """A malformed path or form value should read as a page, not as raw JSON."""
    return HTMLResponse(
        content=render_error_page(request, "Bad Request", "That address or form value was not valid."),
        status_code=400,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Last resort.

    Starlette's default 500 is plain text, which a browser in dark mode paints as white on
    black - the same blackscreen the JSON 404 used to cause. Anything unexpected should
    still look like Nova and offer a way back.
    """
    return HTMLResponse(
        content=render_error_page(
            request, "Something went wrong",
            "That request could not be completed. The Headmaster has been notified.",
        ),
        status_code=500,
    )


@app.get("/favicon.ico")
def favicon():
    # Browsers request this on every page load; answer it rather than logging a 404 each time.
    return Response(status_code=204)


@app.get("/style.css")
def style():
    return Response(content=STYLE_FILE.read_text(), media_type="text/css")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    nav = render_nav(request)
    return HOME_FILE.read_text().replace("{{ nav }}", nav)


@app.get("/characters/new", response_class=HTMLResponse)
def new_character_form(request: Request):
    if get_current_player(request) is None:
        return RedirectResponse(url="/login", status_code=303)
    nav = render_nav(request)
    return CHARACTER_NEW_FILE.read_text().replace("{{ nav }}", nav)


@app.get("/characters", response_class=HTMLResponse)
def character_list(request: Request):
    rows = "".join(render_character_row(c, True) for c in read_characters())
    nav = render_nav(request)
    return LIST_FILE.read_text().replace("{{ rows }}", rows).replace("{{ nav }}", nav)


@app.get("/players", response_class=HTMLResponse)
def player_list(request: Request):
    rows = "".join(f"<tr><td><a href='/player/{p['id']}'>{esc(p['name'])}</a></td></tr>" for p in read_players())
    nav = render_nav(request)
    return PLAYERS_FILE.read_text().replace("{{ rows }}", rows).replace("{{ nav }}", nav)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    options = render_player_options(read_players())
    nav = render_nav(request)
    return LOGIN_FILE.read_text().replace("{{ player_options }}", options).replace("{{ nav }}", nav)


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    request.session["player_id"] = int(form["player_id"])
    return RedirectResponse(url="/", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.post("/enroll")
async def enroll(request: Request):
    form = await request.form()
    conn = get_connection()
    try:
        wants_hm = "is_hm" in form
        hm_exists = conn.execute("SELECT COUNT(*) FROM players WHERE is_hm = 1").fetchone()[0] > 0
        is_hm = 1 if (wants_hm and not hm_exists) else 0
        cursor = conn.execute("INSERT INTO players (name, is_hm) VALUES (?, ?)", (form["name"], is_hm))
        conn.commit()
        player_id = cursor.lastrowid
    finally:
        conn.close()
    request.session["player_id"] = player_id
    export_characters_csv()
    return RedirectResponse(url="/", status_code=303)


@app.get("/player/{id}", response_class=HTMLResponse)
def player_profile(id: int, request: Request):
    player = read_player(id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    rows = "".join(render_character_row(c, False) for c in read_characters_for_player(id))
    nav = render_nav(request)
    return (
        PLAYER_PROFILE_FILE.read_text()
        .replace("{{ name }}", esc(player["name"]))
        .replace("{{ rows }}", rows)
        .replace("{{ nav }}", nav)
    )


def require_owner_or_hm(current_player, character):
    if current_player["id"] != character["player_id"] and not current_player["is_hm"]:
        raise HTTPException(status_code=403, detail="Not permitted to modify this character")


def can_edit_character(request, character):
    current_player = get_current_player(request)
    return current_player is not None and (
        current_player["id"] == character["player_id"] or current_player["is_hm"]
    )


@app.get("/character/{id}/techniques", response_class=HTMLResponse)
def technique_list(id: int, request: Request):
    character = read_character(id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    rows = "".join(render_technique_row(t) for t in read_techniques_for_character(id))
    add_link = (
        f"<p><a href='/character/{id}/techniques/new'>Add Technique</a></p>"
        if can_edit_character(request, character) else ""
    )
    nav = render_nav(request)
    return (
        TECHNIQUES_FILE.read_text()
        .replace("{{ character_name }}", esc(character["name"]))
        .replace("{{ id }}", str(id))
        .replace("{{ rows }}", rows)
        .replace("{{ add_link }}", add_link)
        .replace("{{ nav }}", nav)
    )


@app.get("/character/{id}/techniques/new", response_class=HTMLResponse)
def new_technique_form(id: int, request: Request):
    character = read_character(id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    nav = render_nav(request)
    return (
        TECHNIQUE_NEW_FILE.read_text()
        .replace("{{ id }}", str(id))
        .replace("{{ character_name }}", esc(character["name"]))
        .replace("{{ nav }}", nav)
    )


@app.post("/character/{id}/techniques")
async def create_technique(id: int, request: Request):
    character = read_character(id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    form = await request.form()
    values = to_typed_technique_values(form)
    conn = get_connection()
    try:
        conn.execute(
            f"INSERT INTO techniques (character_id, {', '.join(TECHNIQUE_FIELDS)}) "
            f"VALUES (?, {', '.join('?' for _ in TECHNIQUE_FIELDS)})",
            [id] + values,
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url=f"/character/{id}/techniques", status_code=303)


@app.get("/technique/{id}/edit", response_class=HTMLResponse)
def edit_technique_form(id: int, request: Request):
    technique = read_technique(id)
    if technique is None:
        raise HTTPException(status_code=404, detail="Technique not found")
    character = read_character(technique["character_id"])
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    nav = render_nav(request)
    html = (
        TECHNIQUE_EDIT_FILE.read_text()
        .replace("{{ id }}", str(id))
        .replace("{{ character_id }}", str(character["id"]))
        .replace("{{ character_name }}", esc(character["name"]))
        .replace("{{ nav }}", nav)
    )
    for f in TECHNIQUE_FIELDS:
        html = html.replace(f"{{{{ {f} }}}}", esc(technique[f]))
    return html


@app.post("/technique/{id}/edit")
async def edit_technique(id: int, request: Request):
    technique = read_technique(id)
    if technique is None:
        raise HTTPException(status_code=404, detail="Technique not found")
    character = read_character(technique["character_id"])
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    form = await request.form()
    values = to_typed_technique_values(form)
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE techniques SET {', '.join(f'{f} = ?' for f in TECHNIQUE_FIELDS)} WHERE id = ?",
            values + [id],
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url=f"/character/{character['id']}/techniques", status_code=303)


@app.post("/technique/{id}/delete")
async def delete_technique(id: int, request: Request):
    technique = read_technique(id)
    if technique is None:
        raise HTTPException(status_code=404, detail="Technique not found")
    character = read_character(technique["character_id"])
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    conn = get_connection()
    try:
        conn.execute("DELETE FROM techniques WHERE id = ?", (id,))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url=f"/character/{character['id']}/techniques", status_code=303)


@app.get("/character/{id}/edit", response_class=HTMLResponse)
def edit_character_form(id: int, request: Request):
    character = read_character(id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    if current_player["is_hm"]:
        options = render_player_options(read_players(), selected_id=character["player_id"])
        player_field = f"<label>Player: <select name='player_id' required>{options}</select></label><br />"
    else:
        player_field = ""
    nav = render_nav(request)
    html = (
        EDIT_FILE.read_text()
        .replace("{{ id }}", str(id))
        .replace("{{ player_field }}", player_field)
        .replace("{{ nav }}", nav)
    )
    for f in FIELDS:
        html = html.replace(f"{{{{ {f} }}}}", esc(character[f]))
    return html


@app.post("/character/{id}/edit")
async def edit_character(id: int, request: Request):
    character = read_character(id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    form = await request.form()
    updated = compute_derived_fields({f: form[f] for f in FIELDS})
    values = to_typed_values(updated)
    if current_player["is_hm"] and "player_id" in form:
        player_id = int(form["player_id"])
    else:
        player_id = character["player_id"]
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE characters SET player_id = ?, {', '.join(f'{f} = ?' for f in FIELDS)} WHERE id = ?",
            [player_id] + values + [id],
        )
        conn.commit()
    finally:
        conn.close()
    export_characters_csv()
    return RedirectResponse(url="/characters", status_code=303)


@app.post("/character/{id}/delete")
async def delete_character(id: int, request: Request):
    character = read_character(id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    conn = get_connection()
    try:
        conn.execute("DELETE FROM techniques WHERE character_id = ?", (id,))
        conn.execute("DELETE FROM characters WHERE id = ?", (id,))
        conn.commit()
    finally:
        conn.close()
    export_characters_csv()
    return RedirectResponse(url="/characters", status_code=303)


@app.post("/character")
async def create_character(request: Request):
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    character = compute_derived_fields({f: form[f] for f in FIELDS})
    values = to_typed_values(character)
    conn = get_connection()
    try:
        columns = ["player_id"] + FIELDS
        conn.execute(
            f"INSERT INTO characters ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            [current_player["id"]] + values,
        )
        conn.commit()
    finally:
        conn.close()
    export_characters_csv()
    return RedirectResponse(url="/characters", status_code=303)


@app.get("/enemies", response_class=HTMLResponse)
def enemy_list(request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    rows = "".join(render_creature_row(c) for c in read_creatures())
    nav = render_nav(request)
    return ENEMIES_FILE.read_text().replace("{{ rows }}", rows).replace("{{ nav }}", nav)


@app.get("/enemies/new", response_class=HTMLResponse)
def new_enemy_form(request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    nav = render_nav(request)
    habitat_options = "".join(f"<option value='{h}'>{h}</option>" for h in HABITATS)
    skill_options = "".join(f"<option value='{s}'>{s}</option>" for s in SKILLS)
    return (
        ENEMY_NEW_FILE.read_text()
        .replace("{{ habitat_options }}", habitat_options)
        .replace("{{ skill_options }}", skill_options)
        .replace("{{ nav }}", nav)
    )


@app.post("/enemy")
async def create_enemy(request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    form = await request.form()
    values = to_typed_creature_values(form)
    conn = get_connection()
    try:
        conn.execute(
            f"INSERT INTO creatures ({', '.join(CREATURE_FIELDS)}) VALUES ({', '.join('?' for _ in CREATURE_FIELDS)})",
            values,
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/enemies", status_code=303)


@app.get("/enemy/{id}/edit", response_class=HTMLResponse)
def edit_enemy_form(id: int, request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    creature = read_creature(id)
    if creature is None:
        raise HTTPException(status_code=404, detail="Creature not found")
    nav = render_nav(request)
    habitat_options = "".join(
        f"<option value='{h}'{' selected' if h == creature['habitat'] else ''}>{h}</option>" for h in HABITATS
    )
    skill_options = "".join(
        f"<option value='{s}'{' selected' if s == creature['main_skill'] else ''}>{s}</option>" for s in SKILLS
    )
    html = (
        ENEMY_EDIT_FILE.read_text()
        .replace("{{ id }}", str(id))
        .replace("{{ habitat_options }}", habitat_options)
        .replace("{{ skill_options }}", skill_options)
        .replace("{{ nav }}", nav)
    )
    for f in CREATURE_FIELDS:
        html = html.replace(f"{{{{ {f} }}}}", esc(creature[f]))
    return html


@app.post("/enemy/{id}/edit")
async def edit_enemy(id: int, request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    form = await request.form()
    values = to_typed_creature_values(form)
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE creatures SET {', '.join(f'{f} = ?' for f in CREATURE_FIELDS)} WHERE id = ?",
            values + [id],
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/enemies", status_code=303)


@app.post("/enemy/{id}/delete")
async def delete_enemy(id: int, request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    conn = get_connection()
    try:
        conn.execute("DELETE FROM creatures WHERE id = ?", (id,))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/enemies", status_code=303)


@app.post("/enemy/{id}/generate", response_class=HTMLResponse)
async def generate_enemy(id: int, request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    creature = read_creature(id)
    if creature is None:
        raise HTTPException(status_code=404, detail="Creature not found")
    form = await request.form()
    try:
        threat_level = int(form.get("threat_level", creature["default_threat_level"]))
    except (TypeError, ValueError):
        threat_level = creature["default_threat_level"]
    threat_level = max(1, min(6, threat_level))
    stats, talent_uses, talent_cooldown = generate_creature_stats(creature, threat_level)
    stat_rows = "".join(f"<tr><td>{skill}</td><td>{value}</td></tr>" for skill, value in stats.items())
    nav = render_nav(request)
    return (
        ENEMY_GENERATED_FILE.read_text()
        .replace("{{ name }}", esc(creature["name"]))
        .replace("{{ threat_level }}", str(threat_level))
        .replace("{{ stat_rows }}", stat_rows)
        .replace("{{ talent_name }}", esc(creature["talent_name"]))
        .replace("{{ talent_effect }}", esc(creature["talent_effect"]))
        .replace("{{ talent_uses }}", str(talent_uses))
        .replace("{{ talent_cooldown }}", str(talent_cooldown))
        .replace("{{ drops }}", esc(creature["drops"]))
        .replace("{{ nav }}", nav)
    )


@app.get("/play", response_class=HTMLResponse)
def play_index(request: Request):
    current_player = get_current_player(request)
    rooms = read_rooms()
    if rooms:
        # Open rooms first; closed ones stay listed so their logs remain reachable.
        rooms.sort(key=lambda r: (bool(r["closed_at"]), -r["id"]))
        rows = "".join(
            f"<tr><td><a href='/play/room/{r['id']}'>{esc(r['name'])}</a></td>"
            f"<td>{esc(r['description'])}</td><td>{esc(r['creator_name'])}</td>"
            f"<td>{r['member_count']}</td><td>{esc(format_stamp(r['created_at']))}</td>"
            f"<td>{'Closed' if r['closed_at'] else 'Open'}</td></tr>"
            for r in rooms
        )
        table = (
            "<table><tr><th>Room</th><th>About</th><th>Opened by</th>"
            f"<th>Characters</th><th>Opened</th><th>Status</th></tr>{rows}</table>"
        )
    else:
        table = "<p class='quotes'>No rooms are open. Start one below.</p>"
    if current_player:
        create_form = (
            "<h2>Open a room</h2>"
            "<form method='post' action='/play/rooms'>"
            "<label>Name: <input type='text' name='name' required maxlength='80' /></label>"
            "<label>About: <input type='text' name='description' maxlength='200' /></label>"
            "<button type='submit'>Open</button></form>"
        )
    else:
        create_form = "<p class='quotes'><a href='/login' class='section-link'>Log in to open a room.</a></p>"
    return (
        PLAY_FILE.read_text()
        .replace("{{ rooms }}", table)
        .replace("{{ create_form }}", create_form)
        .replace("{{ nav }}", render_nav(request))
    )


@app.post("/play/rooms")
async def create_room(request: Request):
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    name = (form.get("name") or "").strip()[:80]
    if not name:
        return RedirectResponse(url="/play", status_code=303)
    description = (form.get("description") or "").strip()[:200]
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO rooms (name, description, created_by, created_at) VALUES (?, ?, ?, ?)",
            (name, description, current_player["id"], utc_now()),
        )
        conn.commit()
        room_id = cursor.lastrowid
    finally:
        conn.close()
    return RedirectResponse(url=f"/play/room/{room_id}", status_code=303)


@app.get("/play/room/{id}", response_class=HTMLResponse)
def room_view(id: int, request: Request):
    room = read_room(id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    current_player = get_current_player(request)
    members = read_room_members(id)
    member_rows = "".join(
        f"<tr><td>{esc(m['name'])}</td><td>{esc(m['player_name'])}</td>"
        f"<td>{esc(m['rank'])}</td><td>{esc(m['trait'])}</td></tr>"
        for m in members
    ) or "<tr><td colspan='4'>Nobody has joined yet.</td></tr>"

    enemies = read_room_enemies(id)
    is_hm = bool(current_player and current_player["is_hm"])
    enemy_panel = render_enemy_panel(id, enemies, is_hm, bool(room["closed_at"]))

    is_closed = bool(room["closed_at"])
    if can_close_room(room, current_player):
        if is_closed:
            manage = (
                f"<form method='post' action='/play/room/{id}/reopen'>"
                "<button type='submit'>Reopen room</button></form>"
            )
        else:
            manage = (
                f"<form method='post' action='/play/room/{id}/close' "
                "onsubmit=\"return confirm('Close this room? The log is kept and it can be reopened.')\">"
                "<button type='submit'>Close room</button></form>"
            )
    else:
        manage = ""

    mine = character_in_room(id, current_player["id"]) if current_player else None
    if is_closed:
        note = f"<p class='quotes'>This room was closed {esc(format_stamp(room['closed_at']))}. "
        note += "The log is kept, but nothing new can be posted.</p>"
        if mine:
            note += (
                f"<form method='post' action='/play/room/{id}/leave' "
                "onsubmit=\"return confirm('Leave this room?')\">"
                "<button type='submit'>Leave room</button></form>"
            )
        controls = note + manage
    elif mine:
        roll_count, keep_count = RANK_DICE.get(str(mine["rank"]).strip().title(), (1, 1))
        controls = (
            f"<p>You are in this room as <strong>{esc(mine['name'])}</strong> "
            f"({esc(mine['rank'])} &mdash; {roll_count}d6 keep {keep_count}).</p>"
            f"<form method='post' action='/play/room/{id}/message'>"
            "<label>Say: <input type='text' name='body' required maxlength='500' autocomplete='off' /></label>"
            "<button type='submit'>Send</button></form>"
            f"<form method='post' action='/play/room/{id}/roll'>"
            "<label>Roll: <select name='mode'>"
            f"<option value='rank'>My rank ({roll_count}d6 keep {keep_count})</option>"
            "<option value='d20'>1d20 (Possibility)</option>"
            "<option value='custom'>Custom</option></select></label>"
            f"<label>Custom roll: <input type='number' name='roll_count' min='1' max='{MAX_DICE}' value='{roll_count}' /></label>"
            f"<label>Keep: <input type='number' name='keep_count' min='1' max='{MAX_DICE}' value='{keep_count}' /></label>"
            "<button type='submit'>Roll</button></form>"
            f"<form method='post' action='/play/room/{id}/leave' "
            "onsubmit=\"return confirm('Leave this room?')\">"
            "<button type='submit'>Leave room</button></form>"
        )
    elif current_player:
        available = [
            c for c in read_characters_for_player(current_player["id"])
            if not any(m["id"] == c["id"] for m in members)
        ]
        if available:
            options = "".join(f"<option value='{c['id']}'>{esc(c['name'])}</option>" for c in available)
            controls = (
                f"<form method='post' action='/play/room/{id}/join'>"
                f"<label>Join as: <select name='character_id' required>{options}</select></label>"
                "<button type='submit'>Join</button></form>"
            )
        else:
            controls = (
                "<p class='quotes'>You have no characters yet. "
                "<a href='/characters/new' class='section-link'>Create one</a> to join.</p>"
            )
    else:
        controls = "<p class='quotes'><a href='/login' class='section-link'>Log in to join this room.</a></p>"
    if not is_closed:
        controls += manage

    return (
        ROOM_FILE.read_text()
        .replace("{{ id }}", str(id))
        .replace("{{ room_name }}", esc(room["name"]))
        .replace("{{ room_description }}", esc(room["description"]))
        .replace("{{ member_rows }}", member_rows)
        .replace("{{ enemy_panel }}", enemy_panel)
        .replace("{{ controls }}", controls)
        .replace("{{ messages }}", render_room_messages(read_room_messages(id)))
        .replace("{{ nav }}", render_nav(request))
    )


@app.get("/play/room/{id}/messages", response_class=HTMLResponse)
def room_messages_fragment(id: int):
    """Message log on its own, so the room page can poll for new activity."""
    if read_room(id) is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return render_room_messages(read_room_messages(id))


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


def can_close_room(room, current_player):
    """Only whoever opened the room, or an HM, may close or reopen it."""
    if current_player is None:
        return False
    return room["created_by"] == current_player["id"] or bool(current_player["is_hm"])


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


@app.post("/play/room/{id}/enemy")
async def spawn_room_enemy(id: int, request: Request):
    _room, current_player = require_room_hm(id, request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    try:
        creature_id = int(form["creature_id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Pick a creature to generate.")
    creature = read_creature(creature_id)
    if creature is None:
        raise HTTPException(status_code=404, detail="Creature not found")
    try:
        threat_level = int(form.get("threat_level", creature["default_threat_level"]))
    except (TypeError, ValueError):
        threat_level = creature["default_threat_level"]
    threat_level = max(1, min(6, threat_level))

    stats, talent_uses, talent_cooldown = generate_creature_stats(creature, threat_level)
    # Several of the same creature can be in play at once, so number them per room.
    existing = [e for e in read_room_enemies(id, include_dismissed=True)
                if e["creature_id"] == creature_id]
    name = creature["name"] if not existing else f"{creature['name']} {len(existing) + 1}"

    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO room_enemies (room_id, creature_id, name, threat_level, stats, "
            "talent_name, talent_effect, talent_uses, talent_cooldown, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (id, creature_id, name, threat_level, json.dumps(stats), creature["talent_name"],
             creature["talent_effect"], talent_uses, talent_cooldown, utc_now()),
        )
        conn.commit()
        enemy_id = cursor.lastrowid
    finally:
        conn.close()

    summary = ", ".join(f"{skill} {value}" for skill, value in stats.items())
    post_room_message(
        id, None, "system",
        f"{current_player['name']} sent in {name} ({rank_for_threat(threat_level)}, "
        f"threat {threat_level}) - {summary}.",
    )
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/enemy/{enemy_id}/roll")
async def roll_as_enemy(id: int, enemy_id: int, request: Request):
    _room, current_player = require_room_hm(id, request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    enemy = read_room_enemy(enemy_id)
    if enemy is None or enemy["room_id"] != id or enemy["dismissed_at"]:
        raise HTTPException(status_code=404, detail="Enemy not found in this room")
    form = await request.form()
    mode = form.get("mode", "threat")
    if mode == "d20":
        body = f"rolls <strong>1d20</strong>: <strong>{roll_dice(1, 20)[0]}</strong>"
    else:
        if mode == "threat":
            roll_count, keep_count = RANK_DICE[rank_for_threat(enemy["threat_level"])]
        else:
            try:
                roll_count = int(form.get("roll_count", 1))
                keep_count = int(form.get("keep_count", 1))
            except (TypeError, ValueError):
                roll_count, keep_count = 1, 1
        roll_count = max(1, min(roll_count, MAX_DICE))
        keep_count = max(1, min(keep_count, roll_count))
        all_rolls, kept_sum = roll_and_keep(roll_count, keep_count)
        body = (
            f"rolls <strong>{roll_count}d6 keep {keep_count}</strong>: "
            f"{render_dice_result(all_rolls, keep_count)}&rarr; <strong>{kept_sum}</strong>"
        )
    post_room_message(id, None, "roll", body, enemy_id=enemy_id)
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/enemy/{enemy_id}/dismiss")
async def dismiss_room_enemy(id: int, enemy_id: int, request: Request):
    _room, current_player = require_room_hm(id, request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    enemy = read_room_enemy(enemy_id)
    if enemy is None or enemy["room_id"] != id:
        raise HTTPException(status_code=404, detail="Enemy not found in this room")
    if not enemy["dismissed_at"]:
        conn = get_connection()
        try:
            conn.execute("UPDATE room_enemies SET dismissed_at = ? WHERE id = ?", (utc_now(), enemy_id))
            conn.commit()
        finally:
            conn.close()
        post_room_message(id, None, "system", f"{enemy['name']} left the field.")
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/close")
async def close_room(id: int, request: Request):
    room = read_room(id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    if not can_close_room(room, current_player):
        raise HTTPException(status_code=403, detail="Only whoever opened this room can close it.")
    if not room["closed_at"]:
        conn = get_connection()
        try:
            conn.execute("UPDATE rooms SET closed_at = ? WHERE id = ?", (utc_now(), id))
            conn.commit()
        finally:
            conn.close()
        post_room_message(id, None, "system", f"{current_player['name']} closed the room.")
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/reopen")
async def reopen_room(id: int, request: Request):
    room = read_room(id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    if not can_close_room(room, current_player):
        raise HTTPException(status_code=403, detail="Only whoever opened this room can reopen it.")
    if room["closed_at"]:
        conn = get_connection()
        try:
            conn.execute("UPDATE rooms SET closed_at = NULL WHERE id = ?", (id,))
            conn.commit()
        finally:
            conn.close()
        post_room_message(id, None, "system", f"{current_player['name']} reopened the room.")
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/join")
async def join_room(id: int, request: Request):
    room = read_room(id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    if room["closed_at"]:
        raise HTTPException(status_code=403, detail="This room is closed.")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    try:
        character_id = int(form["character_id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Pick a character to join as")
    character = read_character(character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    if character["player_id"] != current_player["id"] and not current_player["is_hm"]:
        raise HTTPException(status_code=403, detail="That is not your character")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO room_members (room_id, character_id, joined_at) VALUES (?, ?, ?)",
            (id, character_id, utc_now()),
        )
        conn.commit()
    finally:
        conn.close()
    post_room_message(id, character_id, "system", f"{character['name']} entered the room.")
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/leave")
async def leave_room(id: int, request: Request):
    # Leaving stays available after a room closes; only new activity is blocked.
    _room, character = require_room_membership(id, request, allow_closed=True)
    if character is None:
        return RedirectResponse(url="/login", status_code=303)
    conn = get_connection()
    try:
        conn.execute("DELETE FROM room_members WHERE room_id = ? AND character_id = ?", (id, character["id"]))
        conn.commit()
    finally:
        conn.close()
    post_room_message(id, character["id"], "system", f"{character['name']} left the room.")
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/message")
async def send_room_message(id: int, request: Request):
    _room, character = require_room_membership(id, request)
    if character is None:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    body = (form.get("body") or "").strip()[:500]
    if body:
        post_room_message(id, character["id"], "text", body)
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/roll")
async def roll_in_room(id: int, request: Request):
    _room, character = require_room_membership(id, request)
    if character is None:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    mode = form.get("mode", "rank")
    if mode == "d20":
        result = roll_dice(1, 20)[0]
        body = f"rolls <strong>1d20</strong>: <strong>{result}</strong>"
    else:
        if mode == "rank":
            roll_count, keep_count = RANK_DICE.get(str(character["rank"]).strip().title(), (1, 1))
        else:
            try:
                roll_count = int(form.get("roll_count", 1))
                keep_count = int(form.get("keep_count", 1))
            except (TypeError, ValueError):
                roll_count, keep_count = 1, 1
        roll_count = max(1, min(roll_count, MAX_DICE))
        keep_count = max(1, min(keep_count, roll_count))
        all_rolls, kept_sum = roll_and_keep(roll_count, keep_count)
        body = (
            f"rolls <strong>{roll_count}d6 keep {keep_count}</strong>: "
            f"{render_dice_result(all_rolls, keep_count)}&rarr; <strong>{kept_sum}</strong>"
        )
    post_room_message(id, character["id"], "roll", body)
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


# Run the app with uvicorn when this file is executed directly.
def main():
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)


if __name__ == "__main__":
    main()
