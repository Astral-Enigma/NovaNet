"""The migration runner.

These matter more than most tests here: getting this wrong corrupts or discards a real
database on the next deploy, and the failure would land on live data.
"""

import sqlite3

# A database as an early build left it: the tables exist, but the columns that later
# arrived by ALTER TABLE do not, and there is no schema_version.
LEGACY_SCHEMA = """
CREATE TABLE players (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);
CREATE TABLE characters (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, age INTEGER NOT NULL,
  rank TEXT NOT NULL, clan TEXT NOT NULL, house TEXT NOT NULL, trait TEXT NOT NULL,
  trauma INTEGER NOT NULL, pneuma INTEGER NOT NULL, deftness INTEGER NOT NULL,
  handling INTEGER NOT NULL, tenacity INTEGER NOT NULL, wit INTEGER NOT NULL,
  perception INTEGER NOT NULL, composure INTEGER NOT NULL,
  pluck INTEGER NOT NULL DEFAULT 0, potential INTEGER NOT NULL DEFAULT 0);
CREATE TABLE rooms (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '', created_by INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE room_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, room_id INTEGER NOT NULL, character_id INTEGER,
  kind TEXT NOT NULL DEFAULT 'text', body TEXT NOT NULL, created_at TEXT NOT NULL);
INSERT INTO players (name) VALUES ('OldPlayer');
INSERT INTO characters
  (name,age,rank,clan,house,trait,trauma,pneuma,deftness,handling,tenacity,wit,perception,composure)
  VALUES ('Legacy Hero',30,'Master','Varna','Zealot','Pyre',0,10,5,5,5,5,5,5);
INSERT INTO rooms (name, created_by, created_at) VALUES ('Old Room', 1, '2026-01-01T00:00:00+00:00');
INSERT INTO room_messages (room_id, character_id, kind, body, created_at)
  VALUES (1, 1, 'text', 'an old line', '2026-01-01T00:00:00+00:00');
"""


def columns(app_module, table):
    conn = app_module.get_connection()
    try:
        return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


class TestFreshDatabase:
    def test_lands_on_the_latest_version(self, app_module):
        conn = app_module.get_connection()
        try:
            assert app_module.applied_schema_version(conn) == 1
        finally:
            conn.close()

    def test_creates_every_table(self, app_module):
        conn = app_module.get_connection()
        try:
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        finally:
            conn.close()
        assert set(app_module.SNAPSHOT_TABLES) <= names
        assert "schema_version" in names

    def test_nothing_is_pending_afterwards(self, app_module):
        assert app_module.pending_migrations(1) == []


class TestLegacyDatabase:
    """A database from before migrations must be baselined, never rebuilt."""

    def _legacy(self, app_module):
        conn = sqlite3.connect(app_module.DB_FILE)
        conn.executescript(LEGACY_SCHEMA)
        conn.commit()
        conn.close()

    def test_is_baselined_without_losing_rows(self, app_module):
        conn = app_module.get_connection()
        for table in reversed(app_module.SNAPSHOT_TABLES):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute("DROP TABLE IF EXISTS schema_version")
        conn.commit()
        conn.close()
        self._legacy(app_module)

        app_module.run_migrations()

        conn = app_module.get_connection()
        try:
            assert app_module.applied_schema_version(conn) == 1
            assert [r["name"] for r in conn.execute("SELECT name FROM characters")] == ["Legacy Hero"]
            assert [r["body"] for r in conn.execute("SELECT body FROM room_messages")] == ["an old line"]
        finally:
            conn.close()

    def test_adds_the_columns_a_later_build_introduced(self, app_module):
        conn = app_module.get_connection()
        for table in reversed(app_module.SNAPSHOT_TABLES):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute("DROP TABLE IF EXISTS schema_version")
        conn.commit()
        conn.close()
        self._legacy(app_module)

        app_module.run_migrations()

        assert "player_id" in columns(app_module, "characters")
        assert "is_hm" in columns(app_module, "players")
        assert "closed_at" in columns(app_module, "rooms")
        assert "enemy_id" in columns(app_module, "room_messages")

    def test_orphaned_characters_are_given_an_owner(self, app_module):
        conn = app_module.get_connection()
        for table in reversed(app_module.SNAPSHOT_TABLES):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute("DROP TABLE IF EXISTS schema_version")
        conn.commit()
        conn.close()
        self._legacy(app_module)

        app_module.run_migrations()

        conn = app_module.get_connection()
        try:
            row = conn.execute(
                "SELECT players.name AS owner FROM characters "
                "JOIN players ON players.id = characters.player_id").fetchone()
        finally:
            conn.close()
        assert row["owner"] == "Unassigned"


class TestRepeatRuns:
    def test_running_again_changes_nothing(self, app_module):
        def snapshot():
            conn = app_module.get_connection()
            try:
                return {t: conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                        for t in app_module.SNAPSHOT_TABLES}
            finally:
                conn.close()

        before = snapshot()
        for _ in range(3):
            assert app_module.run_migrations() == 1
        assert snapshot() == before


class TestRunner:
    def test_only_higher_numbered_migrations_are_pending(self, app_module):
        assert app_module.pending_migrations(0) != []
        assert app_module.pending_migrations(1) == []
        assert app_module.pending_migrations(99) == []

    def test_a_new_migration_is_applied_and_recorded(self, app_module, tmp_path, monkeypatch):
        migrations = tmp_path / "migrations"
        migrations.mkdir()
        (migrations / "001_initial.sql").write_text(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);")
        (migrations / "002_add_thing.sql").write_text(
            "CREATE TABLE IF NOT EXISTS a_new_thing (id INTEGER PRIMARY KEY, label TEXT);")
        monkeypatch.setattr(app_module, "MIGRATIONS_DIR", migrations)

        assert app_module.run_migrations() == 2

        conn = app_module.get_connection()
        try:
            assert app_module.applied_schema_version(conn) == 2
            assert app_module.table_exists(conn, "a_new_thing")
        finally:
            conn.close()

    def test_files_that_are_not_numbered_are_ignored(self, app_module, tmp_path, monkeypatch):
        migrations = tmp_path / "migrations"
        migrations.mkdir()
        (migrations / "notes.sql").write_text("SELECT 1;")
        monkeypatch.setattr(app_module, "MIGRATIONS_DIR", migrations)
        assert app_module.pending_migrations(0) == []
