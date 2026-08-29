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
