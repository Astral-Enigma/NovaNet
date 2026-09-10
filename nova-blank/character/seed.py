"""Seed data and backups.

The creature catalog ships with the app because it is published reference material. The
snapshot and the CSV are the other direction: they carry a live database through a deploy
that wipes the filesystem, which is the only reason anything survives one.
"""

import csv
import json

import config
from config import CREATURE_FIELDS, CSV_COLUMNS, FIELDS, NUMERIC_FIELDS, SNAPSHOT_TABLES, SNAPSHOT_VERSION
from db import (
    applied_schema_version,
    get_connection,
    get_or_create_unassigned_player,
    run_migrations,
    table_columns,
    table_exists,
)
from queries import utc_now
from rules import normalize_rank, starting_limits

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


def upgrade_version_1_character(row):
    """Bring a character exported before migration 002 up to what 002 makes of it.

    Migration 002 does this in SQL to rows already in a database. A CSV exported before it
    arrives after the migrations have run, so it needs the same treatment here:
    tests/test_character_sheet.py checks the two agree, since two copies of one rule is
    exactly how they drift.
    """
    def as_int(key):
        try:
            return int(row.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    rank = normalize_rank(row.get("rank"))
    trauma_default, pneuma_default = starting_limits(rank)
    trauma_limit = as_int("trauma") if as_int("trauma") > 0 else trauma_default
    pneuma_limit = as_int("pneuma") if as_int("pneuma") > 0 else pneuma_default
    upgraded = dict(row)
    upgraded.update(rank=rank, trauma=0, trauma_limit=trauma_limit,
                    pneuma=pneuma_limit, pneuma_limit=pneuma_limit)
    return upgraded


def migrate_csv_if_needed():
    if not config.CSV_FILE.exists():
        return
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0]
        if count > 0:
            return
        with open(config.CSV_FILE, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # A file without the limit columns predates migration 002, so its trauma and
            # pneuma numbers are really limits.
            version_1 = "trauma_limit" not in (reader.fieldnames or [])
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
            values = to_typed_values(upgrade_version_1_character(row) if version_1 else row)
            conn.execute(
                f"INSERT INTO characters (player_id, {', '.join(FIELDS)}) "
                f"VALUES (?, {', '.join('?' for _ in FIELDS)})",
                [player_id] + values,
            )
        conn.commit()
    finally:
        conn.close()


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


def export_snapshot():
    """Write every table to seed.json, the file the app reloads from on an empty database."""
    conn = get_connection()
    try:
        data = {
            "version": SNAPSHOT_VERSION,
            # Which migration the rows were exported at. Restoring puts them back at that
            # schema and lets the remaining migrations transform them, so a backup taken
            # before a schema change still comes back right after it.
            "schema_version": applied_schema_version(conn),
            "exported_at": utc_now(),
            "tables": {},
        }
        for table in SNAPSHOT_TABLES:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            data["tables"][table] = [dict(row) for row in rows]
    finally:
        conn.close()
    payload = json.dumps(data, indent=1, sort_keys=True)
    try:
        config.SNAPSHOT_FILE.write_text(payload)
    except OSError:
        # A read-only filesystem must not break the app.
        pass
    return payload


# Every snapshot exported before the schema version was recorded came from the schema that
# migration 001 describes, because that is the only one that existed.
LEGACY_SNAPSHOT_SCHEMA_VERSION = 1


def read_snapshot():
    """The committed snapshot, or None if it is missing, unreadable, or has no players."""
    if not config.SNAPSHOT_FILE.exists():
        return None
    try:
        data = json.loads(config.SNAPSHOT_FILE.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not (data.get("tables") or {}).get("players"):
        return None
    return data


def load_snapshot_if_needed():
    """Restore seed.json into an empty database, at the schema it was exported from.

    On a deploy the disk is fresh, so this runs before the database has any schema at all.
    The rows go in at the snapshot's own version and the caller then runs the remaining
    migrations, so data transformations live in one place - the migrations - whether the
    rows arrived by upgrade or by restore. Restoring old rows straight into the newest
    schema would skip those transformations and silently corrupt them.

    Ids are preserved, because techniques, room membership and the message log all
    reference them. Only columns that still exist are restored.
    """
    data = read_snapshot()
    if data is None:
        return False
    snapshot_version = data.get("schema_version") or LEGACY_SNAPSHOT_SCHEMA_VERSION

    conn = get_connection()
    try:
        if table_exists(conn, "players") and conn.execute(
                "SELECT COUNT(*) FROM players").fetchone()[0] > 0:
            return False
        current = applied_schema_version(conn)
    finally:
        conn.close()
    if current is not None and current > snapshot_version:
        # The schema has already moved past the snapshot, so its rows cannot be put back
        # without the transformations in between. A deploy never gets here - its disk has
        # no schema yet - so this only guards against restoring an old backup by hand.
        return False

    run_migrations(up_to=snapshot_version)

    conn = get_connection()
    try:
        tables = data["tables"]
        for table in SNAPSHOT_TABLES:
            rows = tables.get(table) or []
            if not rows or not table_exists(conn, table):
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
        with open(config.CSV_FILE, "w", newline="") as f:
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
