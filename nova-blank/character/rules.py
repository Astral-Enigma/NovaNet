"""Nova's rules, as pure functions over numbers.

Everything the Headmaster's Handbook and the Creature Catalog fix in place: the dice
tables, the Roll/Keep pools, derived stats, and enemy generation. Nothing here reads the
database or a request, which is what makes it cheap to test and safe to build Phase 1 on.
"""

import math
import random

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

# Headmaster's Handbook, Ranking Up: the Academy Points a character must have accumulated
# to reach each rank.
RANK_AP_THRESHOLDS = {
    "Novice": 0,
    "Rookie": 13,
    "Genius": 20,
    "Expert": 34,
    "Veteran": 48,
    "Master": 88,
}

# Trauma counts up from 0 toward the Trauma Limit; the Pneuma Pool counts down from its
# limit. Everyone starts at 15 and 10, and each Rank Up adds 3 to both.
STARTING_TRAUMA_LIMIT = 15
STARTING_PNEUMA_LIMIT = 10
LIMIT_GAIN_PER_RANK = 3


def normalize_rank(value):
    """The canonical rank name for whatever was typed.

    Rank was free text, so the stored values include ' novice' and '1'. Matching ignores
    case and surrounding space, a bare 1-6 reads as a rank number, and anything else falls
    back to Novice, where every character starts. Migration 002 applies the same rule to
    rows already in the database.
    """
    text = str(value or "").strip()
    for rank in RANK_ORDER:
        if text.lower() == rank.lower():
            return rank
    if text.isdigit() and 1 <= int(text) <= len(RANK_ORDER):
        return RANK_ORDER[int(text) - 1]
    return RANK_ORDER[0]


def starting_limits(rank):
    """(Trauma Limit, Pneuma Limit) for a character who has just reached this rank."""
    steps = RANK_ORDER.index(normalize_rank(rank))
    return (STARTING_TRAUMA_LIMIT + LIMIT_GAIN_PER_RANK * steps,
            STARTING_PNEUMA_LIMIT + LIMIT_GAIN_PER_RANK * steps)


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


SKILL_FIELDS = ["deftness", "handling", "tenacity", "wit", "perception", "composure"]


def clean_character(raw, existing=None):
    """A valid character from submitted form values.

    raw is whatever the form sent; existing is the stored character when editing. Missing or
    unreadable numbers fall back to the stored value, then to the Handbook: a new character
    is undamaged, has a full Pneuma Pool, and starts with the limits for its rank. Pluck and
    Potential are always recomputed rather than taken from the form.
    """
    existing = existing or {}
    rank = normalize_rank(raw.get("rank", existing.get("rank")))
    trauma_limit_default, pneuma_limit_default = starting_limits(rank)

    def number(key, default):
        value = raw.get(key)
        if value is None or str(value).strip() == "":
            value = existing.get(key, default)
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return default

    def text(key):
        value = raw.get(key, existing.get(key, ""))
        return "" if value is None else str(value).strip()

    character = {
        "name": text("name"),
        "age": number("age", 0),
        "rank": rank,
        "clan": text("clan"),
        "house": text("house"),
        "trait": text("trait"),
        "trauma_limit": number("trauma_limit", trauma_limit_default),
        "pneuma_limit": number("pneuma_limit", pneuma_limit_default),
        "academy_points": number("academy_points", 0),
        "zel": number("zel", 0),
    }
    character["trauma"] = number("trauma", 0)
    character["pneuma"] = number("pneuma", character["pneuma_limit"])
    for skill in SKILL_FIELDS:
        character[skill] = number(skill, 0)
    total = sum(character[skill] for skill in SKILL_FIELDS)
    character["pluck"] = math.ceil(total / 2)
    character["potential"] = math.ceil(character["pluck"] / 2)
    return character


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
