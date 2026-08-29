"""Rules-engine invariants drawn straight from the Nova manuals."""

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

    def test_dice_pool_is_capped(self, client, app_module):
        """An unbounded pool once built a list big enough to OOM the instance."""
        response = client.post("/dice", data={"rank": "", "roll_count": "999999999", "keep_count": "5"})
        assert response.status_code == 200
        assert response.text.count("<span") <= app_module.MAX_DICE

    def test_keep_never_exceeds_roll(self, client):
        response = client.post("/dice", data={"rank": "", "roll_count": "3", "keep_count": "99"})
        assert response.status_code == 200

    def test_derived_pluck_and_potential(self, app_module):
        character = dict(deftness=3, handling=2, tenacity=4, wit=2, perception=2, composure=3)
        result = app_module.compute_derived_fields(dict(character))
        assert result["pluck"] == "8"      # ceil(16 / 2)
        assert result["potential"] == "4"  # ceil(8 / 2)


class TestEscaping:
    def test_html_is_escaped(self, app_module):
        assert app_module.esc("<script>") == "&lt;script&gt;"
        assert "&#x27;" in app_module.esc("it's")

    def test_js_string_survives_a_breakout_attempt(self, app_module):
        out = app_module.js_string("Bob');alert('x")
        assert "');" not in out
        assert out.startswith("&quot;") and out.endswith("&quot;")

    def test_stored_xss_is_not_served_back(self, player):
        make_character(player, "<script>alert(1)</script>")
        body = player.get("/characters").text
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;" in body
