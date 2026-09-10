"""Rules-engine invariants drawn straight from the Nova manuals."""

import json

import pytest

from conftest import make_character


class TestCreatureStats:
    """Creature Catalog: main skill is (TL)d6 + TL; every other skill starts at a flat 1 at
    Novice and gains 1d6 + 1 per rank above Novice."""

    def test_novice_non_main_skills_are_exactly_one(self, app_module):
        creature = {"main_skill": "Deftness"}
        for _ in range(200):
            stats, _, _ = app_module.generate_creature_stats(creature, 1)
            others = {k: v for k, v in stats.items() if k != "Deftness"}
            assert set(others.values()) == {1}, f"Novice non-main skills must all be 1, got {others}"

    @pytest.mark.parametrize("threat_level", [1, 2, 3, 4, 5, 6])
    def test_skill_bounds_match_the_catalog_formula(self, app_module, threat_level):
        creature = {"main_skill": "Composure"}
        above = threat_level - 1
        main_lo, main_hi = threat_level * 1 + threat_level, threat_level * 6 + threat_level
        other_lo, other_hi = 1 + above * 1 + above, 1 + above * 6 + above
        for _ in range(400):
            stats, _, _ = app_module.generate_creature_stats(creature, threat_level)
            assert main_lo <= stats["Composure"] <= main_hi
            for skill, value in stats.items():
                if skill != "Composure":
                    assert other_lo <= value <= other_hi

    def test_talent_uses_and_cooldown(self, app_module):
        creature = {"main_skill": "Wit"}
        for tl in range(1, 7):
            for _ in range(100):
                _, uses, cooldown = app_module.generate_creature_stats(creature, tl)
                assert 2 * tl <= uses <= 12 * tl          # 2d6 * threat level
                assert cooldown == -(-tl // 2)            # ceil(tl / 2)


class TestDice:
    def test_rank_dice_table_matches_the_handbook(self, app_module):
        assert app_module.RANK_DICE == {
            "Novice": (1, 1), "Rookie": (2, 1), "Genius": (3, 2),
            "Expert": (4, 3), "Veteran": (5, 4), "Master": (6, 5),
        }

    def test_roll_and_keep_sums_the_highest_dice(self, app_module):
        for _ in range(300):
            rolls, kept_sum = app_module.roll_and_keep(5, 3)
            assert len(rolls) == 5
            assert kept_sum == sum(sorted(rolls, reverse=True)[:3])

    def test_dice_page_is_gone(self, client):
        """Rolling lives in Play rooms now; the standalone page was removed."""
        assert client.get("/dice").status_code == 404
        assert "Dice" not in client.get("/").text

    def test_derived_pluck_and_potential(self, app_module):
        character = dict(deftness=3, handling=2, tenacity=4, wit=2, perception=2, composure=3)
        result = app_module.compute_derived_fields(dict(character))
        assert result["pluck"] == "8"      # ceil(16 / 2)
        assert result["potential"] == "4"  # ceil(8 / 2)


class TestEscaping:
    def test_html_is_escaped(self, app_module):
        """Checks the property that matters - nothing that can open a tag or close an
        attribute survives - rather than which entity spelling the library chooses."""
        out = app_module.esc("<script>it's \"quoted\"</script>")
        for dangerous in ("<", ">", "'", '"'):
            assert dangerous not in out, f"{dangerous!r} survived escaping: {out}"

    def test_js_string_survives_a_breakout_attempt(self, app_module):
        import html
        out = app_module.js_string("Bob');alert('x")
        # No raw quote may close the surrounding double-quoted attribute...
        assert '"' not in out and "'" not in out
        # ...and once the browser decodes the attribute, what JavaScript sees is a single
        # JSON string literal with the apostrophes still inside it.
        decoded = html.unescape(out)
        assert json.loads(decoded) == "Bob');alert('x", \
            "must decode to exactly one string literal holding the original text"

    def test_views_and_main_escape_with_the_same_function(self, app_module):
        """main.py once carried its own esc() that shadowed the real one, so the tests above
        were checking a copy that never rendered a page."""
        import sys
        assert app_module.esc is sys.modules["render"].esc
        assert sys.modules["views"].esc is sys.modules["render"].esc

    def test_stored_xss_is_not_served_back(self, player):
        make_character(player, "<script>alert(1)</script>")
        body = player.get("/characters").text
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;" in body
