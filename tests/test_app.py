"""Play rooms, error pages, and the CSV seed round trip."""

import csv
import io

from conftest import make_character


class TestErrorPages:
    """FastAPI's JSON 404 rendered as white-on-black in dark-mode browsers, which is what
    people were reporting as the site blackscreening."""

    def test_unknown_url_returns_html_not_json(self, client):
        response = client.get("/nonexistent")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("text/html")
        assert "Not Found" in response.text
        assert '<html lang="en">' in response.text

    def test_stale_link_returns_html(self, client):
        response = client.get("/character/999/edit")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("text/html")
        assert "Character not found" in response.text

    def test_error_page_offers_a_way_back(self, client):
        assert 'href="/"' in client.get("/nonexistent").text

    def test_favicon_does_not_404(self, client):
        assert client.get("/favicon.ico").status_code == 204


class TestRooms:
    def _open_room(self, client, name="The Pit"):
        client.post("/play/rooms", data={"name": name, "description": "under the dojo"},
                    follow_redirects=False)
        return 1

    def test_play_page_loads_logged_out(self, client):
        assert client.get("/play").status_code == 200

    def test_open_and_join_a_room(self, player):
        cid = make_character(player, "Ryn", rank="Genius")
        room = self._open_room(player)
        response = player.post(f"/play/room/{room}/join", data={"character_id": str(cid)},
                               follow_redirects=False)
        assert response.status_code == 303
        body = player.get(f"/play/room/{room}").text
        assert "Ryn" in body and "entered the room" in body

    def test_rank_roll_uses_the_characters_rank(self, player):
        cid = make_character(player, "Odo", rank="Master")
        room = self._open_room(player)
        player.post(f"/play/room/{room}/join", data={"character_id": str(cid)}, follow_redirects=False)
        player.post(f"/play/room/{room}/roll", data={"mode": "rank"}, follow_redirects=False)
        assert "6d6 keep 5" in player.get(f"/play/room/{room}/messages").text

    def test_d20_roll(self, player):
        cid = make_character(player, "Ryn")
        room = self._open_room(player)
        player.post(f"/play/room/{room}/join", data={"character_id": str(cid)}, follow_redirects=False)
        player.post(f"/play/room/{room}/roll", data={"mode": "d20"}, follow_redirects=False)
        assert "1d20" in player.get(f"/play/room/{room}/messages").text

    def test_custom_roll_is_capped(self, player, app_module):
        cid = make_character(player, "Ryn")
        room = self._open_room(player)
        player.post(f"/play/room/{room}/join", data={"character_id": str(cid)}, follow_redirects=False)
        player.post(f"/play/room/{room}/roll",
                    data={"mode": "custom", "roll_count": "999999", "keep_count": "3"},
                    follow_redirects=False)
        assert f"{app_module.MAX_DICE}d6" in player.get(f"/play/room/{room}/messages").text

    def test_messages_are_escaped(self, player):
        cid = make_character(player, "Ryn")
        room = self._open_room(player)
        player.post(f"/play/room/{room}/join", data={"character_id": str(cid)}, follow_redirects=False)
        player.post(f"/play/room/{room}/message", data={"body": "<img src=x onerror=alert(1)>"},
                    follow_redirects=False)
        log = player.get(f"/play/room/{room}/messages").text
        assert "<img src=x" not in log
        assert "&lt;img" in log

    def test_non_member_cannot_post_or_roll(self, player):
        make_character(player, "Ryn")
        room = self._open_room(player)  # opened but never joined
        assert player.post(f"/play/room/{room}/message", data={"body": "hi"},
                           follow_redirects=False).status_code == 403
        assert player.post(f"/play/room/{room}/roll", data={"mode": "rank"},
                           follow_redirects=False).status_code == 403

    def test_logged_out_visitor_is_sent_to_login(self, client):
        client.post("/enroll", data={"name": "Owner"}, follow_redirects=False)
        make_character(client, "Ryn")
        self._open_room(client)
        client.post("/logout", follow_redirects=False)
        response = client.post("/play/room/1/message", data={"body": "hi"}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_missing_room_is_a_styled_404(self, client):
        response = client.get("/play/room/999")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("text/html")

    def test_cannot_join_as_someone_elses_character(self, client):
        client.post("/enroll", data={"name": "Owner"}, follow_redirects=False)
        cid = make_character(client, "Ryn")
        self._open_room(client)
        client.post("/logout", follow_redirects=False)
        client.post("/enroll", data={"name": "Interloper"}, follow_redirects=False)
        response = client.post("/play/room/1/join", data={"character_id": str(cid)}, follow_redirects=False)
        assert response.status_code == 403


class TestClosingRooms:
    def _joined_room(self, client, name="Ryn"):
        cid = make_character(client, name)
        client.post("/play/rooms", data={"name": "The Pit", "description": ""},
                    follow_redirects=False)
        client.post("/play/room/1/join", data={"character_id": str(cid)}, follow_redirects=False)
        return 1

    def test_opener_can_close(self, player):
        room = self._joined_room(player)
        assert player.post(f"/play/room/{room}/close", follow_redirects=False).status_code == 303
        body = player.get(f"/play/room/{room}").text
        assert "closed the room" in body
        assert "This room was closed" in body

    def test_closing_blocks_new_activity(self, player):
        room = self._joined_room(player)
        player.post(f"/play/room/{room}/close", follow_redirects=False)
        assert player.post(f"/play/room/{room}/message", data={"body": "hi"},
                           follow_redirects=False).status_code == 403
        assert player.post(f"/play/room/{room}/roll", data={"mode": "rank"},
                           follow_redirects=False).status_code == 403

    def test_closing_blocks_new_joins(self, client):
        client.post("/enroll", data={"name": "Owner"}, follow_redirects=False)
        self._joined_room(client)
        client.post("/play/room/1/close", follow_redirects=False)
        client.post("/logout", follow_redirects=False)
        client.post("/enroll", data={"name": "Latecomer"}, follow_redirects=False)
        cid = make_character(client, "Odo")
        response = client.post("/play/room/1/join", data={"character_id": str(cid)},
                               follow_redirects=False)
        assert response.status_code == 403

    def test_log_survives_closing(self, player):
        room = self._joined_room(player)
        player.post(f"/play/room/{room}/message", data={"body": "a line of play"},
                    follow_redirects=False)
        player.post(f"/play/room/{room}/close", follow_redirects=False)
        assert "a line of play" in player.get(f"/play/room/{room}/messages").text

    def test_members_can_still_leave_a_closed_room(self, player):
        room = self._joined_room(player)
        player.post(f"/play/room/{room}/close", follow_redirects=False)
        assert player.post(f"/play/room/{room}/leave", follow_redirects=False).status_code == 303

    def test_non_opener_cannot_close(self, client):
        client.post("/enroll", data={"name": "Owner"}, follow_redirects=False)
        self._joined_room(client)
        client.post("/logout", follow_redirects=False)
        client.post("/enroll", data={"name": "Bystander"}, follow_redirects=False)
        assert client.post("/play/room/1/close", follow_redirects=False).status_code == 403

    def test_hm_can_close_someone_elses_room(self, client):
        client.post("/enroll", data={"name": "Owner"}, follow_redirects=False)
        self._joined_room(client)
        client.post("/logout", follow_redirects=False)
        client.post("/enroll", data={"name": "Head", "is_hm": "1"}, follow_redirects=False)
        assert client.post("/play/room/1/close", follow_redirects=False).status_code == 303

    def test_reopen_restores_activity(self, player):
        room = self._joined_room(player)
        player.post(f"/play/room/{room}/close", follow_redirects=False)
        assert player.post(f"/play/room/{room}/reopen", follow_redirects=False).status_code == 303
        assert player.post(f"/play/room/{room}/message", data={"body": "back on"},
                           follow_redirects=False).status_code == 303
        assert "back on" in player.get(f"/play/room/{room}/messages").text

    def test_closing_twice_is_harmless(self, player):
        room = self._joined_room(player)
        player.post(f"/play/room/{room}/close", follow_redirects=False)
        player.post(f"/play/room/{room}/close", follow_redirects=False)
        assert player.get(f"/play/room/{room}/messages").text.count("closed the room") == 1

    def test_status_shows_on_the_play_listing(self, player):
        room = self._joined_room(player)
        assert "Open" in player.get("/play").text
        player.post(f"/play/room/{room}/close", follow_redirects=False)
        assert "Closed" in player.get("/play").text

    def test_logged_out_close_goes_to_login(self, client):
        client.post("/enroll", data={"name": "Owner"}, follow_redirects=False)
        self._joined_room(client)
        client.post("/logout", follow_redirects=False)
        response = client.post("/play/room/1/close", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_closing_a_missing_room_is_a_styled_404(self, player):
        response = player.post("/play/room/999/close", follow_redirects=False)
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("text/html")


class TestCreatureCatalog:
    """The Catalog ships with the app so enemy generation survives a wipe."""

    def test_catalog_is_seeded(self, app_module):
        conn = app_module.get_connection()
        count = conn.execute("SELECT COUNT(*) FROM creatures").fetchone()[0]
        names = [r["name"] for r in conn.execute("SELECT name FROM creatures")]
        conn.close()
        assert count == len(app_module.CATALOG_SEED) == 17
        assert "Minotaur" in names and "Kah'clth-Kahban" in names

    def test_every_seeded_main_skill_is_generatable(self, app_module):
        """A main skill outside SKILLS would silently never get the main-skill roll."""
        for row in app_module.CATALOG_SEED:
            assert row[3] in app_module.SKILLS, f"{row[0]} has main skill {row[3]}"

    def test_every_seeded_threat_level_is_in_range(self, app_module):
        for row in app_module.CATALOG_SEED:
            assert 1 <= row[4] <= 6, f"{row[0]} has threat level {row[4]}"

    def test_habitats_match_the_catalog_groupings(self, app_module):
        for row in app_module.CATALOG_SEED:
            assert row[2] in app_module.HABITATS, f"{row[0]} has habitat {row[2]}"

    def test_seeding_does_not_overwrite_an_edited_catalog(self, app_module):
        conn = app_module.get_connection()
        conn.execute("DELETE FROM creatures")
        conn.execute(
            f"INSERT INTO creatures ({', '.join(app_module.CREATURE_FIELDS)}) "
            f"VALUES ({', '.join('?' for _ in app_module.CREATURE_FIELDS)})",
            ("Homebrew", "d", "Damned", "Wit", 3, "t", "e", "drop"),
        )
        conn.commit()
        conn.close()

        app_module.seed_creature_catalog()

        conn = app_module.get_connection()
        names = [r["name"] for r in conn.execute("SELECT name FROM creatures")]
        conn.close()
        assert names == ["Homebrew"]


class TestRoomEnemies:
    def _hm_room(self, client):
        client.post("/enroll", data={"name": "Head", "is_hm": "1"}, follow_redirects=False)
        client.post("/play/rooms", data={"name": "The Pit", "description": ""},
                    follow_redirects=False)
        return 1

    def _creature_id(self, app_module, name="Minotaur"):
        conn = app_module.get_connection()
        row = conn.execute("SELECT id FROM creatures WHERE name = ?", (name,)).fetchone()
        conn.close()
        return row["id"]

    def test_hm_can_send_in_an_enemy(self, client, app_module):
        room = self._hm_room(client)
        cid = self._creature_id(app_module)
        response = client.post(f"/play/room/{room}/enemy", data={"creature_id": str(cid)},
                               follow_redirects=False)
        assert response.status_code == 303
        body = client.get(f"/play/room/{room}").text
        assert "Minotaur" in body and "sent in Minotaur" in body

    def test_threat_level_defaults_to_the_catalog_value(self, client, app_module):
        room = self._hm_room(client)
        client.post(f"/play/room/{room}/enemy",
                    data={"creature_id": str(self._creature_id(app_module, "Alkalym"))},
                    follow_redirects=False)
        enemies = app_module.read_room_enemies(room)
        assert enemies[0]["threat_level"] == 4  # Alkalym is Expert in the Catalog

    def test_threat_level_is_clamped(self, client, app_module):
        room = self._hm_room(client)
        client.post(f"/play/room/{room}/enemy",
                    data={"creature_id": str(self._creature_id(app_module)), "threat_level": "99"},
                    follow_redirects=False)
        assert app_module.read_room_enemies(room)[0]["threat_level"] == 6

    def test_rolling_as_an_enemy_uses_its_threat_dice(self, client, app_module):
        room = self._hm_room(client)
        client.post(f"/play/room/{room}/enemy",
                    data={"creature_id": str(self._creature_id(app_module, "Phoenix"))},
                    follow_redirects=False)
        enemy = app_module.read_room_enemies(room)[0]
        client.post(f"/play/room/{room}/enemy/{enemy['id']}/roll", data={"mode": "threat"},
                    follow_redirects=False)
        log = client.get(f"/play/room/{room}/messages").text
        assert "6d6 keep 5" in log       # Phoenix is Master
        assert "Phoenix" in log          # attributed to the enemy, not the player

    def test_enemy_d20_roll(self, client, app_module):
        room = self._hm_room(client)
        client.post(f"/play/room/{room}/enemy",
                    data={"creature_id": str(self._creature_id(app_module))}, follow_redirects=False)
        enemy = app_module.read_room_enemies(room)[0]
        client.post(f"/play/room/{room}/enemy/{enemy['id']}/roll", data={"mode": "d20"},
                    follow_redirects=False)
        assert "1d20" in client.get(f"/play/room/{room}/messages").text

    def test_duplicates_are_numbered(self, client, app_module):
        room = self._hm_room(client)
        cid = self._creature_id(app_module)
        for _ in range(3):
            client.post(f"/play/room/{room}/enemy", data={"creature_id": str(cid)},
                        follow_redirects=False)
        names = [e["name"] for e in app_module.read_room_enemies(room)]
        assert names == ["Minotaur", "Minotaur 2", "Minotaur 3"]

    def test_dismissing_removes_it_from_the_field(self, client, app_module):
        room = self._hm_room(client)
        client.post(f"/play/room/{room}/enemy",
                    data={"creature_id": str(self._creature_id(app_module))}, follow_redirects=False)
        enemy = app_module.read_room_enemies(room)[0]
        client.post(f"/play/room/{room}/enemy/{enemy['id']}/dismiss", follow_redirects=False)
        assert app_module.read_room_enemies(room) == []
        assert "left the field" in client.get(f"/play/room/{room}/messages").text

    def test_a_dismissed_enemy_cannot_roll(self, client, app_module):
        room = self._hm_room(client)
        client.post(f"/play/room/{room}/enemy",
                    data={"creature_id": str(self._creature_id(app_module))}, follow_redirects=False)
        enemy = app_module.read_room_enemies(room)[0]
        client.post(f"/play/room/{room}/enemy/{enemy['id']}/dismiss", follow_redirects=False)
        response = client.post(f"/play/room/{room}/enemy/{enemy['id']}/roll",
                               data={"mode": "threat"}, follow_redirects=False)
        assert response.status_code == 404

    def test_a_student_cannot_send_in_enemies(self, client, app_module):
        self._hm_room(client)
        cid = self._creature_id(app_module)
        client.post("/logout", follow_redirects=False)
        client.post("/enroll", data={"name": "Student"}, follow_redirects=False)
        response = client.post("/play/room/1/enemy", data={"creature_id": str(cid)},
                               follow_redirects=False)
        assert response.status_code == 403

    def test_a_student_cannot_roll_as_an_enemy(self, client, app_module):
        room = self._hm_room(client)
        client.post(f"/play/room/{room}/enemy",
                    data={"creature_id": str(self._creature_id(app_module))}, follow_redirects=False)
        enemy = app_module.read_room_enemies(room)[0]
        client.post("/logout", follow_redirects=False)
        client.post("/enroll", data={"name": "Student"}, follow_redirects=False)
        response = client.post(f"/play/room/{room}/enemy/{enemy['id']}/roll",
                               data={"mode": "threat"}, follow_redirects=False)
        assert response.status_code == 403

    def test_logged_out_is_sent_to_login(self, client, app_module):
        self._hm_room(client)
        cid = self._creature_id(app_module)
        client.post("/logout", follow_redirects=False)
        response = client.post("/play/room/1/enemy", data={"creature_id": str(cid)},
                               follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_a_closed_room_takes_no_enemies(self, client, app_module):
        room = self._hm_room(client)
        cid = self._creature_id(app_module)
        client.post(f"/play/room/{room}/close", follow_redirects=False)
        response = client.post(f"/play/room/{room}/enemy", data={"creature_id": str(cid)},
                               follow_redirects=False)
        assert response.status_code == 403

    def test_an_enemy_from_another_room_is_not_reachable(self, client, app_module):
        room = self._hm_room(client)
        client.post(f"/play/room/{room}/enemy",
                    data={"creature_id": str(self._creature_id(app_module))}, follow_redirects=False)
        enemy = app_module.read_room_enemies(room)[0]
        client.post("/play/rooms", data={"name": "Other", "description": ""}, follow_redirects=False)
        response = client.post(f"/play/room/2/enemy/{enemy['id']}/roll", data={"mode": "threat"},
                               follow_redirects=False)
        assert response.status_code == 404

    def test_students_see_the_field_but_not_the_controls(self, client, app_module):
        room = self._hm_room(client)
        client.post(f"/play/room/{room}/enemy",
                    data={"creature_id": str(self._creature_id(app_module))}, follow_redirects=False)
        hm_body = client.get(f"/play/room/{room}").text
        assert "Generate" in hm_body and "Dismiss" in hm_body
        client.post("/logout", follow_redirects=False)
        client.post("/enroll", data={"name": "Student"}, follow_redirects=False)
        student_body = client.get(f"/play/room/{room}").text
        assert "Minotaur" in student_body
        assert "Dismiss" not in student_body and "Send in" not in student_body


class TestCsvSeed:
    def test_export_includes_owning_player(self, player, app_module):
        make_character(player, "Ryn", rank="Genius")
        rows = list(csv.DictReader(io.StringIO(app_module.CSV_FILE.read_text())))
        assert rows and rows[0]["player"] == "Kira"
        assert rows[0]["name"] == "Ryn"

    def test_export_endpoint_requires_auth(self, client):
        response = client.get("/export/characters.csv", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_export_token_grants_access(self, client, app_module, monkeypatch):
        monkeypatch.setenv("NOVANET_EXPORT_TOKEN", "s3cret")
        response = client.get("/export/characters.csv?token=s3cret", follow_redirects=False)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")

    def test_wrong_token_is_rejected(self, client, monkeypatch):
        monkeypatch.setenv("NOVANET_EXPORT_TOKEN", "s3cret")
        response = client.get("/export/characters.csv?token=wrong", follow_redirects=False)
        assert response.status_code == 303

    def test_unset_token_cannot_be_matched_by_an_empty_one(self, client, monkeypatch):
        monkeypatch.delenv("NOVANET_EXPORT_TOKEN", raising=False)
        assert client.get("/export/characters.csv?token=", follow_redirects=False).status_code == 303

    def test_ownership_survives_a_reseed(self, player, app_module):
        """The whole point of the seed file: a wiped database comes back with owners intact."""
        make_character(player, "Ryn", rank="Genius")
        exported = app_module.CSV_FILE.read_text()

        conn = app_module.get_connection()
        conn.execute("DELETE FROM characters")
        conn.execute("DELETE FROM players")
        conn.commit()
        conn.close()

        app_module.CSV_FILE.write_text(exported)
        app_module.migrate_csv_if_needed()

        conn = app_module.get_connection()
        rows = conn.execute(
            "SELECT characters.name, players.name AS owner FROM characters "
            "JOIN players ON players.id = characters.player_id"
        ).fetchall()
        conn.close()
        assert [(r["name"], r["owner"]) for r in rows] == [("Ryn", "Kira")]

    def test_legacy_csv_without_player_column_still_loads(self, app_module):
        app_module.CSV_FILE.write_text(
            "name,age,rank,clan,house,trait,trauma,pneuma,deftness,handling,"
            "tenacity,wit,perception,composure,pluck,potential\n"
            "Jarrett,29,Master,Varna,0,0,200,0,0,0,0,0,0,0,0,0\n"
        )
        conn = app_module.get_connection()
        conn.execute("DELETE FROM characters")
        conn.commit()
        conn.close()

        app_module.migrate_csv_if_needed()

        conn = app_module.get_connection()
        row = conn.execute(
            "SELECT characters.name, players.name AS owner FROM characters "
            "JOIN players ON players.id = characters.player_id"
        ).fetchone()
        conn.close()
        assert row["name"] == "Jarrett"
        assert row["owner"] == "Unassigned"
