"""Phase 1, first slice: Rank, Trauma and Pneuma against their limits, AP and Zel.

The part that matters most is the backup path. A deploy builds an empty database and then
restores seed.json into it, so a migration that transforms existing rows would run on an
empty table and the old backup would land untransformed. These tests hold that closed.
"""

import json

from conftest import make_character

# A character exactly as the live site stored them before migration 002: one trauma and
# one pneuma number, which players filled in with their limits, and free-text rank.
OLD_FORMAT_SNAPSHOT = {
    "version": 1,
    # no schema_version: every snapshot exported before it was recorded is version 1
    "tables": {
        "players": [{"id": 1, "name": "Jarrett", "is_hm": 0}],
        "characters": [
            {"id": 1, "player_id": 1, "name": "Sleepy", "age": 20, "rank": "Rookie",
             "clan": "Varna", "house": "Emperor", "trait": "Pyre", "trauma": 15, "pneuma": 13,
             "deftness": 3, "handling": 2, "tenacity": 4, "wit": 2, "perception": 2,
             "composure": 3, "pluck": 8, "potential": 4},
            {"id": 2, "player_id": 1, "name": "Lowercase", "age": 20, "rank": " novice",
             "clan": "0", "house": "0", "trait": "0", "trauma": 0, "pneuma": 0,
             "deftness": 0, "handling": 0, "tenacity": 0, "wit": 0, "perception": 0,
             "composure": 0, "pluck": 0, "potential": 0},
            {"id": 3, "player_id": 1, "name": "Numbered", "age": 20, "rank": "6",
             "clan": "0", "house": "0", "trait": "0", "trauma": 0, "pneuma": 0,
             "deftness": 0, "handling": 0, "tenacity": 0, "wit": 0, "perception": 0,
             "composure": 0, "pluck": 0, "potential": 0},
        ],
    },
}


def fresh_deploy(app_module, snapshot):
    """Reproduce a deploy: no schema at all, then restore, then migrate."""
    import pathlib
    db_file = pathlib.Path(app_module.config.DB_FILE)
    for suffix in ("", "-wal", "-shm"):
        pathlib.Path(str(db_file) + suffix).unlink(missing_ok=True)
    app_module.SNAPSHOT_FILE.write_text(json.dumps(snapshot))
    app_module.config.SNAPSHOT_FILE = app_module.SNAPSHOT_FILE
    restored = app_module.load_snapshot_if_needed()
    app_module.run_migrations()
    conn = app_module.get_connection()
    try:
        return restored, {r["name"]: dict(r) for r in conn.execute("SELECT * FROM characters")}
    finally:
        conn.close()


class TestDeployPreservesCharacters:
    def test_the_real_startup_restores_before_migrating(self, app_module):
        """Goes through main.start() itself, so reordering the startup fails this test.
        The other tests here drive the steps by hand and would not notice."""
        import pathlib
        db_file = pathlib.Path(app_module.config.DB_FILE)
        for suffix in ("", "-wal", "-shm"):
            pathlib.Path(str(db_file) + suffix).unlink(missing_ok=True)
        app_module.SNAPSHOT_FILE.write_text(json.dumps(OLD_FORMAT_SNAPSHOT))
        app_module.config.SNAPSHOT_FILE = app_module.SNAPSHOT_FILE

        app_module.start()

        conn = app_module.get_connection()
        row = conn.execute("SELECT trauma, trauma_limit, pneuma, pneuma_limit FROM characters "
                           "WHERE name = 'Sleepy'").fetchone()
        conn.close()
        assert tuple(row) == (0, 15, 13, 13), "the old limit must not land as current damage"

    def test_an_old_backup_is_restored_then_migrated(self, app_module):
        restored, chars = fresh_deploy(app_module, OLD_FORMAT_SNAPSHOT)
        assert restored
        sleepy = chars["Sleepy"]
        # what the player typed were limits; the character is undamaged with a full pool
        assert (sleepy["trauma"], sleepy["trauma_limit"]) == (0, 15)
        assert (sleepy["pneuma"], sleepy["pneuma_limit"]) == (13, 13)

    def test_restoring_straight_into_the_new_schema_would_have_corrupted_it(self, app_module):
        """The failure this ordering exists to prevent: skip the restore-first step and the
        old trauma value lands as current damage, one hit from death."""
        import pathlib
        db_file = pathlib.Path(app_module.config.DB_FILE)
        for suffix in ("", "-wal", "-shm"):
            pathlib.Path(str(db_file) + suffix).unlink(missing_ok=True)
        app_module.run_migrations()  # newest schema first - the wrong order
        app_module.SNAPSHOT_FILE.write_text(json.dumps(OLD_FORMAT_SNAPSHOT))
        app_module.config.SNAPSHOT_FILE = app_module.SNAPSHOT_FILE
        # the guard refuses rather than restore rows the migrations never saw
        assert app_module.load_snapshot_if_needed() is False

    def test_free_text_rank_is_normalised(self, app_module):
        _, chars = fresh_deploy(app_module, OLD_FORMAT_SNAPSHOT)
        assert chars["Lowercase"]["rank"] == "Novice"
        assert chars["Numbered"]["rank"] == "Master"

    def test_an_unset_limit_takes_the_handbook_value_for_the_rank(self, app_module):
        _, chars = fresh_deploy(app_module, OLD_FORMAT_SNAPSHOT)
        assert (chars["Lowercase"]["trauma_limit"], chars["Lowercase"]["pneuma_limit"]) == (15, 10)
        # Master is five Rank Ups above Novice: 15 + 15 and 10 + 15
        assert (chars["Numbered"]["trauma_limit"], chars["Numbered"]["pneuma_limit"]) == (30, 25)

    def test_a_new_backup_records_its_schema_version(self, app_module):
        data = json.loads(app_module.export_snapshot())
        conn = app_module.get_connection()
        try:
            assert data["schema_version"] == app_module.applied_schema_version(conn)
        finally:
            conn.close()

    def test_a_new_backup_round_trips_without_being_transformed_twice(self, player, app_module):
        """A backup taken after 002 must come back as-is, not have 002 applied again."""
        cid = make_character(player, "Ryn", rank="Genius", trauma_limit="21", pneuma_limit="16")
        player.post(f"/character/{cid}/edit", data={
            "name": "Ryn", "age": "17", "rank": "Genius", "clan": "Kin", "house": "Hermit",
            "trait": "Shin", "trauma": "7", "trauma_limit": "21", "pneuma": "4",
            "pneuma_limit": "16", "deftness": "3", "handling": "2", "tenacity": "4", "wit": "2",
            "perception": "2", "composure": "3", "academy_points": "5", "zel": "120"},
            follow_redirects=False)
        snapshot = json.loads(app_module.export_snapshot())
        _, chars = fresh_deploy(app_module, snapshot)
        ryn = chars["Ryn"]
        assert (ryn["trauma"], ryn["trauma_limit"], ryn["pneuma"], ryn["pneuma_limit"]) == (7, 21, 4, 16)
        assert (ryn["academy_points"], ryn["zel"]) == (5, 120)


class TestRankRules:
    def test_thresholds_match_the_handbook(self, app_module):
        import sys
        rules = sys.modules["rules"]
        assert rules.RANK_AP_THRESHOLDS == {
            "Novice": 0, "Rookie": 13, "Genius": 20, "Expert": 34, "Veteran": 48, "Master": 88}

    def test_starting_limits_add_three_per_rank(self, app_module):
        import sys
        rules = sys.modules["rules"]
        assert rules.starting_limits("Novice") == (15, 10)
        assert rules.starting_limits("Rookie") == (18, 13)
        assert rules.starting_limits("Master") == (30, 25)

    def test_normalize_rank(self, app_module):
        import sys
        norm = sys.modules["rules"].normalize_rank
        assert norm("  vEtErAn ") == "Veteran"
        assert norm("3") == "Genius"
        assert norm("7") == "Novice"
        assert norm("wizard") == "Novice"
        assert norm(None) == "Novice"


class TestSheetThroughTheUi:
    def test_a_new_character_is_undamaged_with_a_full_pool(self, player, app_module):
        cid = make_character(player, "Odo", rank="Rookie", trauma_limit="18", pneuma_limit="13")
        conn = app_module.get_connection()
        row = dict(conn.execute("SELECT * FROM characters WHERE id = ?", (cid,)).fetchone())
        conn.close()
        assert (row["trauma"], row["trauma_limit"]) == (0, 18)
        assert (row["pneuma"], row["pneuma_limit"]) == (13, 13)

    def test_rank_typed_badly_is_stored_canonically(self, player, app_module):
        cid = make_character(player, "Odo", rank=" expert ")
        conn = app_module.get_connection()
        assert conn.execute("SELECT rank FROM characters WHERE id = ?", (cid,)).fetchone()[0] == "Expert"
        conn.close()

    def test_limits_default_from_rank_when_left_out(self, player, app_module):
        cid = make_character(player, "Odo", rank="Genius")
        conn = app_module.get_connection()
        row = conn.execute("SELECT trauma_limit, pneuma_limit FROM characters WHERE id = ?",
                           (cid,)).fetchone()
        conn.close()
        assert (row[0], row[1]) == (21, 16)

    def test_the_table_shows_current_against_limit(self, player, app_module):
        make_character(player, "Odo", rank="Rookie", trauma_limit="18", pneuma_limit="13")
        body = player.get("/characters").text
        assert "0 / 18" in body and "13 / 13" in body
        assert "<th>AP</th>" in body and "<th>Zel</th>" in body

    def test_header_and_cells_stay_the_same_width(self, player, app_module):
        """They come from one list now; if they ever split, rows misalign silently."""
        import re
        make_character(player, "Odo")
        body = player.get("/characters").text
        header = re.search(r"<tr><th>.*?</tr>", body, re.S).group(0)
        row = re.search(r"<tr><td>.*?</tr>", body, re.S).group(0)
        assert header.count("<th>") == row.count("<td>")

    def test_edit_form_offers_the_six_ranks(self, player, app_module):
        cid = make_character(player, "Odo", rank="Genius")
        body = player.get(f"/character/{cid}/edit").text
        for rank in ("Novice", "Rookie", "Genius", "Expert", "Veteran", "Master"):
            assert f'value="{rank}"' in body
        assert 'value="Genius" selected' in body


class TestTheTwoUpgradePathsAgree:
    """Migration 002 upgrades rows in SQL; a pre-002 CSV is upgraded in Python because it
    arrives after the migrations have run. Two copies of one rule drift unless something
    holds them together - this is that something."""

    FIELDS = ("rank", "trauma", "trauma_limit", "pneuma", "pneuma_limit")

    def _via_migration(self, app_module):
        _, chars = fresh_deploy(app_module, OLD_FORMAT_SNAPSHOT)
        return {name: tuple(c[f] for f in self.FIELDS) for name, c in chars.items()}

    def _via_csv_upgrade(self, app_module):
        import sys
        upgrade = sys.modules["seed"].upgrade_version_1_character
        out = {}
        for row in OLD_FORMAT_SNAPSHOT["tables"]["characters"]:
            up = upgrade(dict(row))
            out[row["name"]] = tuple(up[f] for f in self.FIELDS)
        return out

    def test_sql_and_python_produce_the_same_characters(self, app_module):
        assert self._via_migration(app_module) == self._via_csv_upgrade(app_module)

    def test_a_pre_002_csv_loads_as_limits_not_damage(self, app_module):
        """The regression: this path used to put the old trauma number in as current
        damage and leave the new limit column at zero."""
        import pathlib
        db_file = pathlib.Path(app_module.config.DB_FILE)
        for suffix in ("", "-wal", "-shm"):
            pathlib.Path(str(db_file) + suffix).unlink(missing_ok=True)
        app_module.run_migrations()
        app_module.CSV_FILE.write_text(
            "player,player_is_hm,name,age,rank,clan,house,trait,trauma,pneuma,"
            "deftness,handling,tenacity,wit,perception,composure,pluck,potential\n"
            "Jarrett,0,Sleepy,20,Rookie,Varna,Emperor,Pyre,15,13,3,2,4,2,2,3,8,4\n")
        app_module.config.CSV_FILE = app_module.CSV_FILE
        app_module.migrate_csv_if_needed()
        conn = app_module.get_connection()
        row = conn.execute("SELECT trauma, trauma_limit, pneuma, pneuma_limit FROM characters").fetchone()
        conn.close()
        assert tuple(row) == (0, 15, 13, 13)


class TestCreationDropdowns:
    """Clan, House and Trait are chosen from the Handbook's lists, as Rank is."""

    HANDBOOK = {
        "clan": ["Varna", "Kin", "Forged", "Stricken", "Haunted"],
        "house": ["Zealot", "Hermit", "Patron", "Serpent", "Alchemist", "Emperor"],
        "trait": ["Shin", "Zin", "Smog", "Pyre", "Null"],
    }

    def _options(self, body, name):
        import re
        select = re.search(r'<select name="%s".*?</select>' % name, body, re.S).group(0)
        return re.findall(r'<option value="([^"]+)"', select), select

    def test_the_lists_match_the_handbook(self, app_module):
        import sys
        rules = sys.modules["rules"]
        assert rules.CLANS == self.HANDBOOK["clan"]
        assert rules.HOUSES == self.HANDBOOK["house"]
        assert rules.TRAITS == self.HANDBOOK["trait"]

    def test_the_creation_form_offers_each_list(self, player):
        body = player.get("/characters/new").text
        for field, expected in self.HANDBOOK.items():
            options, _ = self._options(body, field)
            assert options == expected, f"{field} offered {options}"

    def test_nothing_is_preselected_on_a_new_character(self, player):
        """A default would let someone skip a choice the Handbook makes them take."""
        body = player.get("/characters/new").text
        for field in self.HANDBOOK:
            _, select = self._options(body, field)
            assert 'value="" disabled selected' in select

    def test_editing_keeps_the_existing_choice_selected(self, player):
        cid = make_character(player, "Ryn", clan="Kin", house="Hermit", trait="Shin")
        body = player.get(f"/character/{cid}/edit").text
        assert 'value="Kin" selected' in body
        assert 'value="Hermit" selected' in body
        assert 'value="Shin" selected' in body

    def test_an_unset_value_asks_to_be_chosen_on_edit(self, player, app_module):
        cid = make_character(player, "Ryn")
        conn = app_module.get_connection()
        conn.execute("UPDATE characters SET house = '0' WHERE id = ?", (cid,))
        conn.commit()
        conn.close()
        _, select = self._options(player.get(f"/character/{cid}/edit").text, "house")
        assert 'value="" disabled selected' in select

    def test_case_and_spacing_are_forgiven(self, player, app_module):
        cid = make_character(player, "Ryn", clan="  varna ", house="ZEALOT", trait="pyre")
        conn = app_module.get_connection()
        row = conn.execute("SELECT clan, house, trait FROM characters WHERE id = ?", (cid,)).fetchone()
        conn.close()
        assert tuple(row) == ("Varna", "Zealot", "Pyre")

    def test_a_value_outside_the_list_is_not_stored(self, player, app_module):
        """The dropdown is only the front door; the server enforces the list too, so a
        hand-built request cannot store an invented House."""
        cid = make_character(player, "Ryn", clan="Dragonkin", house="Gryffindor", trait="Wind")
        conn = app_module.get_connection()
        row = conn.execute("SELECT clan, house, trait FROM characters WHERE id = ?", (cid,)).fetchone()
        conn.close()
        assert tuple(row) == ("", "", "")
