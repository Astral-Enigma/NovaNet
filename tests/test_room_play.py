"""What the first live session asked for: enemy health, a modifier on rolls, the Headmaster
speaking without joining, and the character sheet visible in a room."""

import sys

from conftest import make_character


def rules():
    return sys.modules["rules"]


def hm_room(client):
    client.post("/enroll", data={"name": "Head", "is_hm": "1"}, follow_redirects=False)
    client.post("/play/rooms", data={"name": "The Pit", "description": ""}, follow_redirects=False)
    return 1


def creature_id(app_module, name="Minotaur"):
    conn = app_module.get_connection()
    try:
        return conn.execute("SELECT id FROM creatures WHERE name = ?", (name,)).fetchone()["id"]
    finally:
        conn.close()


def set_uses_techniques(app_module, name, value):
    conn = app_module.get_connection()
    conn.execute("UPDATE creatures SET uses_techniques = ? WHERE name = ?", (value, name))
    conn.commit()
    conn.close()


def spawn(client, app_module, name="Minotaur", threat=None):
    data = {"creature_id": str(creature_id(app_module, name))}
    if threat:
        data["threat_level"] = str(threat)
    client.post("/play/room/1/enemy", data=data, follow_redirects=False)
    return app_module.read_room_enemies(1)[-1]


def log(client):
    return client.get("/play/room/1/messages").text


class TestCreatureResourceRule:
    """Headmaster's ruling: Trauma Limit 15 + (Threat Level)d6; a Pneuma Pool of 15 +
    (Threat Level)d6 only for a creature that can use techniques."""

    def test_trauma_limit_bounds(self, app_module):
        for level in range(1, 7):
            for _ in range(300):
                trauma, _ = rules().generate_creature_resources(level, False)
                assert 15 + level <= trauma <= 15 + 6 * level

    def test_no_pool_without_techniques(self, app_module):
        for level in range(1, 7):
            assert rules().generate_creature_resources(level, False)[1] == 0

    def test_pool_bounds_with_techniques(self, app_module):
        for level in range(1, 7):
            for _ in range(300):
                _, pneuma = rules().generate_creature_resources(level, True)
                assert 15 + level <= pneuma <= 15 + 6 * level

    def test_catalog_creatures_start_unable_to_use_techniques(self, app_module):
        """The Catalog never says which can, so none are marked until the HM does."""
        conn = app_module.get_connection()
        marked = conn.execute("SELECT COUNT(*) FROM creatures WHERE uses_techniques = 1").fetchone()[0]
        conn.close()
        assert marked == 0


class TestEnemyHealth:
    def test_a_spawned_enemy_is_undamaged_with_a_rolled_limit(self, client, app_module):
        hm_room(client)
        enemy = spawn(client, app_module, "Minotaur", threat=3)
        assert enemy["trauma"] == 0
        assert 15 + 3 <= enemy["trauma_limit"] <= 15 + 18
        assert enemy["pneuma_limit"] == 0

    def test_a_technique_user_gets_a_full_pool(self, client, app_module):
        hm_room(client)
        set_uses_techniques(app_module, "Siren", 1)
        enemy = spawn(client, app_module, "Siren", threat=2)
        assert 15 + 2 <= enemy["pneuma_limit"] <= 15 + 12
        assert enemy["pneuma"] == enemy["pneuma_limit"]

    def test_the_log_announces_its_health(self, client, app_module):
        hm_room(client)
        enemy = spawn(client, app_module)
        assert f"Trauma {enemy['trauma_limit']}" in log(client)

    def test_hm_deals_damage_and_it_is_logged(self, client, app_module):
        hm_room(client)
        enemy = spawn(client, app_module)
        client.post(f"/play/room/1/enemy/{enemy['id']}/health", data={"trauma_change": "5"},
                    follow_redirects=False)
        assert app_module.read_room_enemy(enemy["id"])["trauma"] == 5
        assert f"takes 5 Trauma (5 / {enemy['trauma_limit']})" in log(client)

    def test_trauma_can_pass_its_limit_and_says_so(self, client, app_module):
        """Past the limit is where Pluck Saves and deaths happen - the table's call, so the
        app records it and flags it rather than stopping it."""
        hm_room(client)
        enemy = spawn(client, app_module)
        over = enemy["trauma_limit"] + 4
        client.post(f"/play/room/1/enemy/{enemy['id']}/health", data={"trauma_change": str(over)},
                    follow_redirects=False)
        assert app_module.read_room_enemy(enemy["id"])["trauma"] == over
        assert "at or past the Trauma Limit" in log(client)
        assert "at-limit" in client.get("/play/room/1").text

    def test_healing_stops_at_zero(self, client, app_module):
        hm_room(client)
        enemy = spawn(client, app_module)
        client.post(f"/play/room/1/enemy/{enemy['id']}/health", data={"trauma_change": "-50"},
                    follow_redirects=False)
        assert app_module.read_room_enemy(enemy["id"])["trauma"] == 0

    def test_pneuma_cannot_exceed_its_pool(self, client, app_module):
        hm_room(client)
        set_uses_techniques(app_module, "Siren", 1)
        enemy = spawn(client, app_module, "Siren")
        client.post(f"/play/room/1/enemy/{enemy['id']}/health", data={"pneuma_change": "-3"},
                    follow_redirects=False)
        assert app_module.read_room_enemy(enemy["id"])["pneuma"] == enemy["pneuma_limit"] - 3
        assert f"spends 3 Pneuma" in log(client)
        client.post(f"/play/room/1/enemy/{enemy['id']}/health", data={"pneuma_change": "99"},
                    follow_redirects=False)
        assert app_module.read_room_enemy(enemy["id"])["pneuma"] == enemy["pneuma_limit"]

    def test_a_creature_without_a_pool_ignores_pneuma(self, client, app_module):
        hm_room(client)
        enemy = spawn(client, app_module)
        client.post(f"/play/room/1/enemy/{enemy['id']}/health", data={"pneuma_change": "5"},
                    follow_redirects=False)
        assert app_module.read_room_enemy(enemy["id"])["pneuma"] == 0
        # no pool, so nothing about Pneuma - not on arrival, not after the change
        assert "Pneuma" not in log(client)

    def test_a_student_cannot_damage_an_enemy(self, client, app_module):
        hm_room(client)
        enemy = spawn(client, app_module)
        client.post("/logout", follow_redirects=False)
        client.post("/enroll", data={"name": "Student"}, follow_redirects=False)
        response = client.post(f"/play/room/1/enemy/{enemy['id']}/health",
                               data={"trauma_change": "5"}, follow_redirects=False)
        assert response.status_code == 403

    def test_existing_enemies_get_a_limit_from_the_migration(self, app_module):
        """Enemies spawned before 003 had no Trauma; 003 rolls them one."""
        import pathlib
        conn = app_module.get_connection()
        conn.execute("INSERT INTO players (id, name) VALUES (1, 'Head')")
        conn.execute("INSERT INTO rooms (id, name, created_by, created_at) VALUES (1, 'R', 1, 'x')")
        conn.execute("INSERT INTO room_enemies (room_id, creature_id, name, threat_level, stats, "
                     "created_at) VALUES (1, 1, 'Old Gorgon', 2, '{}', 'x')")
        conn.execute("UPDATE schema_version SET version = 2")
        conn.commit()
        conn.close()
        # replay only 003's data step against the pre-existing row
        sql = (pathlib.Path(app_module.config.MIGRATIONS_DIR) / "003_creature_health.sql").read_text()
        update = sql[sql.index("UPDATE room_enemies"):]
        conn = app_module.get_connection()
        conn.executescript(update)
        limit = conn.execute("SELECT trauma_limit FROM room_enemies WHERE name = 'Old Gorgon'").fetchone()[0]
        conn.close()
        assert 15 + 2 <= limit <= 15 + 12


class TestCatalogSetting:
    def test_the_checkbox_saves_and_clears(self, client, app_module):
        client.post("/enroll", data={"name": "Head", "is_hm": "1"}, follow_redirects=False)
        cid = creature_id(app_module, "Siren")
        creature = dict(app_module.read_creature(cid))
        form = {k: str(creature[k]) for k in ("name", "description", "habitat", "main_skill",
                                               "default_threat_level", "talent_name",
                                               "talent_effect", "drops")}
        client.post(f"/enemy/{cid}/edit", data={**form, "uses_techniques": "1"}, follow_redirects=False)
        assert app_module.read_creature(cid)["uses_techniques"] == 1
        client.post(f"/enemy/{cid}/edit", data=form, follow_redirects=False)   # box unticked
        assert app_module.read_creature(cid)["uses_techniques"] == 0

    def test_the_catalog_table_shows_it(self, client, app_module):
        client.post("/enroll", data={"name": "Head", "is_hm": "1"}, follow_redirects=False)
        body = client.get("/enemies").text
        assert "<th>Techniques</th>" in body and "<td>No</td>" in body


class TestRollModifier:
    def test_resolve_roll_applies_it(self, app_module):
        for _ in range(200):
            r = rules().resolve_roll("d20", 1, 1, 2)
            assert r["total"] == r["subtotal"] + 2 and 3 <= r["total"] <= 22
            r = rules().resolve_roll("pool", 3, 2, -1)
            assert r["total"] == r["subtotal"] - 1

    def test_it_is_bounded(self, app_module):
        assert rules().parse_modifier("500") == 99
        assert rules().parse_modifier("-500") == -99
        assert rules().parse_modifier("abc") == 0
        assert rules().parse_modifier("") == 0

    def test_a_player_roll_shows_it_in_the_log(self, player):
        cid = make_character(player, "Ryn", rank="Genius")
        player.post("/play/rooms", data={"name": "R", "description": ""}, follow_redirects=False)
        player.post("/play/room/1/join", data={"character_id": str(cid)}, follow_redirects=False)
        player.post("/play/room/1/roll", data={"mode": "rank", "modifier": "2"}, follow_redirects=False)
        body = log(player)
        assert "3d6 keep 2 +2" in body and "+2 = " in body

    def test_a_d20_with_a_negative_modifier(self, player):
        cid = make_character(player, "Ryn")
        player.post("/play/rooms", data={"name": "R", "description": ""}, follow_redirects=False)
        player.post("/play/room/1/join", data={"character_id": str(cid)}, follow_redirects=False)
        player.post("/play/room/1/roll", data={"mode": "d20", "modifier": "-3"}, follow_redirects=False)
        assert "1d20 -3" in log(player)

    def test_no_modifier_reads_as_before(self, player):
        cid = make_character(player, "Ryn", rank="Master")
        player.post("/play/rooms", data={"name": "R", "description": ""}, follow_redirects=False)
        player.post("/play/room/1/join", data={"character_id": str(cid)}, follow_redirects=False)
        player.post("/play/room/1/roll", data={"mode": "rank"}, follow_redirects=False)
        body = log(player)
        assert "6d6 keep 5</strong>" in body and " = " not in body.split("6d6 keep 5")[-1][:80]

    def test_an_enemy_roll_takes_it_too(self, client, app_module):
        hm_room(client)
        enemy = spawn(client, app_module, "Minotaur", threat=1)
        client.post(f"/play/room/1/enemy/{enemy['id']}/roll", data={"mode": "threat", "modifier": "4"},
                    follow_redirects=False)
        assert "1d6 keep 1 +4" in log(client)


class TestNarration:
    def test_the_hm_narrates_without_joining(self, client, app_module):
        hm_room(client)
        response = client.post("/play/room/1/narrate", data={"body": "The lights go out."},
                               follow_redirects=False)
        assert response.status_code == 303
        body = log(client)
        assert "Headmaster:" in body and "The lights go out." in body
        assert app_module.read_room_members(1) == [], "narrating must not join the room"

    def test_the_form_is_offered_to_the_hm_only(self, client, app_module):
        hm_room(client)
        assert "Narrate as the Headmaster" in client.get("/play/room/1").text
        client.post("/logout", follow_redirects=False)
        client.post("/enroll", data={"name": "Student"}, follow_redirects=False)
        assert "Narrate as the Headmaster" not in client.get("/play/room/1").text

    def test_a_student_cannot_narrate(self, client, app_module):
        hm_room(client)
        client.post("/logout", follow_redirects=False)
        client.post("/enroll", data={"name": "Student"}, follow_redirects=False)
        response = client.post("/play/room/1/narrate", data={"body": "I am the HM now"},
                               follow_redirects=False)
        assert response.status_code == 403
        assert "I am the HM now" not in log(client)

    def test_not_in_a_closed_room(self, client, app_module):
        hm_room(client)
        client.post("/play/room/1/close", follow_redirects=False)
        response = client.post("/play/room/1/narrate", data={"body": "Hello"}, follow_redirects=False)
        assert response.status_code == 403

    def test_narration_is_escaped(self, client, app_module):
        hm_room(client)
        client.post("/play/room/1/narrate", data={"body": "<script>alert(1)</script>"},
                    follow_redirects=False)
        body = log(client)
        assert "<script>alert(1)" not in body and "&lt;script&gt;" in body


class TestSheetInRoom:
    def _joined(self, player, **overrides):
        cid = make_character(player, "Ryn", rank="Genius", **overrides)
        player.post("/play/rooms", data={"name": "R", "description": ""}, follow_redirects=False)
        player.post("/play/room/1/join", data={"character_id": str(cid)}, follow_redirects=False)
        return cid

    def test_your_sheet_is_in_the_room(self, player):
        self._joined(player, trauma_limit="21", pneuma_limit="16")
        body = player.get("/play/room/1").text
        assert "Your sheet" in body
        assert "0 / 21" in body and "16 / 16" in body
        assert "3d6 keep 2" in body

    def test_no_sheet_until_you_join(self, player):
        make_character(player, "Ryn")
        player.post("/play/rooms", data={"name": "R", "description": ""}, follow_redirects=False)
        assert "Your sheet" not in player.get("/play/room/1").text

    def test_the_room_shows_everyones_health(self, player):
        self._joined(player, trauma_limit="21", pneuma_limit="16")
        body = player.get("/play/room/1").text
        assert "<th>Trauma</th>" in body and "<th>Pneuma</th>" in body

    def test_a_player_changes_their_own_health_and_it_persists(self, player, app_module):
        cid = self._joined(player, trauma_limit="21", pneuma_limit="16")
        player.post(f"/play/room/1/character/{cid}/health",
                    data={"trauma_change": "4", "pneuma_change": "-2"}, follow_redirects=False)
        c = app_module.read_character(cid)
        assert (c["trauma"], c["pneuma"]) == (4, 14)
        # it is the real sheet, so the characters table shows it too
        assert "4 / 21" in player.get("/characters").text

    def test_a_player_cannot_change_someone_elses(self, client, app_module):
        client.post("/enroll", data={"name": "Owner"}, follow_redirects=False)
        cid = make_character(client, "Ryn")
        client.post("/play/rooms", data={"name": "R", "description": ""}, follow_redirects=False)
        client.post("/play/room/1/join", data={"character_id": str(cid)}, follow_redirects=False)
        client.post("/logout", follow_redirects=False)
        client.post("/enroll", data={"name": "Other"}, follow_redirects=False)
        response = client.post(f"/play/room/1/character/{cid}/health", data={"trauma_change": "9"},
                               follow_redirects=False)
        assert response.status_code == 403
        assert app_module.read_character(cid)["trauma"] == 0

    def test_the_hm_can_change_anyones(self, client, app_module):
        client.post("/enroll", data={"name": "Owner"}, follow_redirects=False)
        cid = make_character(client, "Ryn")
        client.post("/play/rooms", data={"name": "R", "description": ""}, follow_redirects=False)
        client.post("/play/room/1/join", data={"character_id": str(cid)}, follow_redirects=False)
        client.post("/logout", follow_redirects=False)
        client.post("/enroll", data={"name": "Head", "is_hm": "1"}, follow_redirects=False)
        client.post(f"/play/room/1/character/{cid}/health", data={"trauma_change": "6"},
                    follow_redirects=False)
        assert app_module.read_character(cid)["trauma"] == 6

    def test_only_characters_in_the_room(self, player, app_module):
        cid = make_character(player, "Ryn")
        player.post("/play/rooms", data={"name": "R", "description": ""}, follow_redirects=False)
        response = player.post(f"/play/room/1/character/{cid}/health", data={"trauma_change": "1"},
                               follow_redirects=False)
        assert response.status_code == 404
