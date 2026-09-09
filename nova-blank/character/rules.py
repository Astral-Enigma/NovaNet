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
