-- 002: Trauma and Pneuma become current values measured against a limit, Rank is one of
-- the six Handbook ranks, and characters gain Academy Points and Zel.
--
-- Until now each character had a single trauma and pneuma number, and players filled them
-- in with their limits: every real character in play had Trauma 15 and Pneuma 10, the
-- Handbook's starting values, and the one Rookie had Pneuma 13, which is 10 plus one Rank
-- Up. So those numbers move into the new limit columns, and the current values start
-- from an undamaged character with a full Pneuma Pool.
--
-- This runs against any database that reaches version 2, including one just restored from
-- a backup exported at version 1, which is why restoring happens before migrating.

ALTER TABLE characters ADD COLUMN trauma_limit INTEGER NOT NULL DEFAULT 15;
ALTER TABLE characters ADD COLUMN pneuma_limit INTEGER NOT NULL DEFAULT 10;
ALTER TABLE characters ADD COLUMN academy_points INTEGER NOT NULL DEFAULT 0;
ALTER TABLE characters ADD COLUMN zel INTEGER NOT NULL DEFAULT 0;

-- Rank was free text. Match it ignoring case and surrounding space, read a bare 1-6 as a
-- rank number, and start anything unrecognisable at Novice. rules.normalize_rank applies
-- the same rule to new input.
UPDATE characters SET rank = CASE lower(trim(rank))
    WHEN 'novice'  THEN 'Novice'
    WHEN 'rookie'  THEN 'Rookie'
    WHEN 'genius'  THEN 'Genius'
    WHEN 'expert'  THEN 'Expert'
    WHEN 'veteran' THEN 'Veteran'
    WHEN 'master'  THEN 'Master'
    WHEN '1' THEN 'Novice'
    WHEN '2' THEN 'Rookie'
    WHEN '3' THEN 'Genius'
    WHEN '4' THEN 'Expert'
    WHEN '5' THEN 'Veteran'
    WHEN '6' THEN 'Master'
    ELSE 'Novice'
END;

-- The old numbers become the limits. A zero or negative one was never a real limit - it
-- means the field was left at nothing - so those take the Handbook value for the
-- character's rank instead: 15 and 10, plus 3 for each rank above Novice.
UPDATE characters SET
    trauma_limit = CASE WHEN trauma > 0 THEN trauma ELSE 15 + 3 * (CASE rank
        WHEN 'Rookie' THEN 1 WHEN 'Genius' THEN 2 WHEN 'Expert' THEN 3
        WHEN 'Veteran' THEN 4 WHEN 'Master' THEN 5 ELSE 0 END) END,
    pneuma_limit = CASE WHEN pneuma > 0 THEN pneuma ELSE 10 + 3 * (CASE rank
        WHEN 'Rookie' THEN 1 WHEN 'Genius' THEN 2 WHEN 'Expert' THEN 3
        WHEN 'Veteran' THEN 4 WHEN 'Master' THEN 5 ELSE 0 END) END;

-- Nobody has been tracking damage in the app, so every character is undamaged, and every
-- Pneuma Pool is full.
UPDATE characters SET trauma = 0, pneuma = pneuma_limit;
