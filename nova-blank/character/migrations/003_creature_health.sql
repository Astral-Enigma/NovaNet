-- 003: creatures get Trauma, and a Pneuma Pool if they can use techniques.
--
-- The Creature Catalog never gives a creature Trauma or Pneuma. The Headmaster's ruling:
-- every creature has a Trauma Limit of 15 plus a d6 per Threat Level, and a creature that
-- can use techniques has a Pneuma Pool of 15 plus a d6 per Threat Level. Which creatures can
-- use techniques is not recorded anywhere, so it is a per-creature setting, off until the
-- Headmaster turns it on.

ALTER TABLE creatures ADD COLUMN uses_techniques INTEGER NOT NULL DEFAULT 0;

-- Current values against a limit, the same shape as a character's (migration 002).
ALTER TABLE room_enemies ADD COLUMN trauma INTEGER NOT NULL DEFAULT 0;
ALTER TABLE room_enemies ADD COLUMN trauma_limit INTEGER NOT NULL DEFAULT 15;
ALTER TABLE room_enemies ADD COLUMN pneuma INTEGER NOT NULL DEFAULT 0;
ALTER TABLE room_enemies ADD COLUMN pneuma_limit INTEGER NOT NULL DEFAULT 0;

-- Enemies already on a field were generated before creatures had Trauma, so they roll their
-- Trauma Limit now: 15, plus one d6 for each Threat Level. No creature could use techniques
-- when they were sent in, so none of them has a Pneuma Pool.
UPDATE room_enemies SET trauma_limit = 15
    + (CASE WHEN threat_level >= 1 THEN abs(random()) % 6 + 1 ELSE 0 END)
    + (CASE WHEN threat_level >= 2 THEN abs(random()) % 6 + 1 ELSE 0 END)
    + (CASE WHEN threat_level >= 3 THEN abs(random()) % 6 + 1 ELSE 0 END)
    + (CASE WHEN threat_level >= 4 THEN abs(random()) % 6 + 1 ELSE 0 END)
    + (CASE WHEN threat_level >= 5 THEN abs(random()) % 6 + 1 ELSE 0 END)
    + (CASE WHEN threat_level >= 6 THEN abs(random()) % 6 + 1 ELSE 0 END);
