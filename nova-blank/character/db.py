"""The database: connections, write-ahead logging, and schema migrations."""

import sqlite3

import config

def get_connection():
    # busy_timeout and synchronous are per-connection, so they belong here. journal_mode is
    # a property of the database file itself and is set once in enable_wal(); re-issuing it
    # per request costs a lock acquisition on every single call.
    conn = sqlite3.connect(config.DB_FILE, timeout=30)
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
    conn = sqlite3.connect(config.DB_FILE, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
    finally:
        conn.close()


def table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone() is not None


def ensure_legacy_columns(conn):
    """Bring a database created before migrations up to what 001 produces.

    These columns arrived as ALTER TABLE in earlier builds, so an older database has the
    tables but not the columns, and CREATE TABLE IF NOT EXISTS will not add them. Each check
    is idempotent, so running this against an already-current database does nothing.
    """
    additions = [
        ("characters", "player_id", "ALTER TABLE characters ADD COLUMN player_id INTEGER"),
        ("players", "is_hm", "ALTER TABLE players ADD COLUMN is_hm INTEGER NOT NULL DEFAULT 0"),
        ("rooms", "closed_at", "ALTER TABLE rooms ADD COLUMN closed_at TEXT"),
        ("room_messages", "enemy_id", "ALTER TABLE room_messages ADD COLUMN enemy_id INTEGER"),
    ]
    for table, column, statement in additions:
        if not table_exists(conn, table):
            continue
        columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
        if column in columns:
            continue
        conn.execute(statement)
        if table == "characters" and column == "player_id":
            unassigned_id = get_or_create_unassigned_player(conn)
            conn.execute("UPDATE characters SET player_id = ? WHERE player_id IS NULL", (unassigned_id,))
    conn.commit()


def applied_schema_version(conn):
    """The migration number this database is at, or None if it predates the system."""
    if not table_exists(conn, "schema_version"):
        return None
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    return row["version"] if row else 0


def pending_migrations(version):
    found = []
    for path in sorted(config.MIGRATIONS_DIR.glob("*.sql")):
        try:
            number = int(path.name.split("_", 1)[0])
        except ValueError:
            continue
        if number > version:
            found.append((number, path))
    return found


def run_migrations():
    """Apply every migration the database has not seen yet.

    A database from before this system already holds the schema 001 describes, so it is
    baselined rather than rebuilt: 001's CREATE TABLE IF NOT EXISTS statements are no-ops
    against it, and ensure_legacy_columns fills in the columns an older CREATE lacks.
    """
    conn = get_connection()
    try:
        version = applied_schema_version(conn)
        legacy = version is None and table_exists(conn, "players")
        if version is None:
            version = 0
        for number, path in pending_migrations(version):
            conn.executescript(path.read_text())
            if legacy:
                ensure_legacy_columns(conn)
            conn.execute("DELETE FROM schema_version")
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (number,))
            conn.commit()
            version = number
        return version
    finally:
        conn.close()


def get_or_create_unassigned_player(conn):
    row = conn.execute("SELECT id FROM players WHERE name = 'Unassigned'").fetchone()
    if row:
        return row["id"]
    cursor = conn.execute("INSERT INTO players (name) VALUES ('Unassigned')")
    conn.commit()
    return cursor.lastrowid


def table_columns(conn, table):
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
