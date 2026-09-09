-- 001: the schema as it stood when migrations were introduced.
--
-- Written IF NOT EXISTS so that baselining an existing database is a no-op. A database
-- created before this system also needs ensure_legacy_columns(), which adds the columns
-- that arrived later as ALTER TABLE and so are absent from an older CREATE.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    is_hm INTEGER NOT NULL DEFAULT 0
);

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
);

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
);

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
);

CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_by INTEGER NOT NULL REFERENCES players(id),
    created_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS room_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    character_id INTEGER NOT NULL REFERENCES characters(id),
    joined_at TEXT NOT NULL,
    UNIQUE (room_id, character_id)
);

CREATE TABLE IF NOT EXISTS room_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    character_id INTEGER REFERENCES characters(id),
    kind TEXT NOT NULL DEFAULT 'text',
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    -- last, matching the ALTER TABLE that added it, so a fresh database and one
    -- migrated from an older build end up with identical column order
    enemy_id INTEGER REFERENCES room_enemies(id)
);

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
);
