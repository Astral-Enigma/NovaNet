"""Paths, field lists, and the session secret.

Everything here is read at import. Tests reload the app modules per test so that
NOVANET_DATA_DIR is picked up fresh, and they reassign CSV_FILE and SNAPSHOT_FILE on this
module, so other modules reach them as config.CSV_FILE rather than binding a copy at
import time.
"""

import os
import secrets
from pathlib import Path

APP_DIR = Path(__file__).parent

# Hosts like Render give each deploy a fresh, empty filesystem, so anything written next to
# this file is wiped every time the app ships. NOVANET_DATA_DIR points the database and the
# session secret at a persistent disk instead; it defaults to alongside the code so local
# development is unchanged.
DATA_DIR = Path(os.environ.get("NOVANET_DATA_DIR", APP_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)

MIGRATIONS_DIR = APP_DIR / "migrations"
SECRET_KEY_FILE = DATA_DIR / "session_secret.txt"
DB_FILE = DATA_DIR / "characters.db"
STYLE_FILE = APP_DIR / "style.css"

CSV_FILE = APP_DIR / "characters.csv"
# The complete backup. characters.csv stays as a legacy fallback for databases seeded
# before snapshots existed.
SNAPSHOT_FILE = APP_DIR / "seed.json"

FIELDS = ["name", "age", "rank", "clan", "house", "trait", "trauma", "pneuma", "deftness",
          "handling", "tenacity", "wit", "perception", "composure", "pluck", "potential"]
NUMERIC_FIELDS = ["age", "trauma", "pneuma", "deftness", "handling", "tenacity", "wit",
                  "perception", "composure", "pluck", "potential"]
TECHNIQUE_FIELDS = ["name", "description", "toll", "type", "category", "effect", "burst",
                    "duration"]
CREATURE_FIELDS = ["name", "description", "habitat", "main_skill", "default_threat_level",
                   "talent_name", "talent_effect", "drops"]

# The seed CSV carries the owning player alongside each character so that ownership and HM
# status survive a reseed. Older files without these columns still load; their characters
# fall back to the Unassigned player.
CSV_COLUMNS = ["player", "player_is_hm"] + FIELDS

# Everything a table creates. Order matters on restore: a row's referents load first.
SNAPSHOT_TABLES = ["players", "characters", "techniques", "creatures",
                   "rooms", "room_enemies", "room_members", "room_messages"]
SNAPSHOT_VERSION = 1


def load_session_secret():
    """A freshly generated secret on every start would log every user out on restart, so
    prefer the environment and fall back to a secret persisted beside the database."""
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
