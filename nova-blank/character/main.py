# Character creator FastAPI app.
# Allows creating characters with any fields defined in FIELDS, saved to a SQLite database.
# Install dependencies on Ubuntu:
#   sudo apt update && sudo apt install -y python3-pip
#   pip3 install fastapi uvicorn python-multipart
# Run:
#   uv run --with fastapi --with uvicorn --with python-multipart --with itsdangerous python3 main.py

import json

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

import config
import db
from config import (
    CREATURE_FIELDS,
    CSV_COLUMNS,
    FIELDS,
    NUMERIC_FIELDS,
    SNAPSHOT_TABLES,
    SNAPSHOT_VERSION,
    TECHNIQUE_FIELDS,
)
from db import (
    applied_schema_version,
    enable_wal,
    get_connection,
    get_or_create_unassigned_player,
    pending_migrations,
    run_migrations,
    table_columns,
    table_exists,
)
from render import esc, js_string, render, safe
from guards import (
    can_close_room,
    can_edit_character,
    export_token_is_valid,
    require_hm_login,
    require_owner_or_hm,
    require_room_hm,
    require_room_membership,
)
from views import (
    CHARACTER_HEADERS,
    nav_links_for,
    page,
    render_character_row,
    render_creature_row,
    render_dice_result,
    render_enemy_panel,
    render_error_page,
    render_player_options,
    render_room_messages,
    render_technique_row,
)
from queries import (
    character_in_room,
    format_stamp,
    get_current_player,
    post_room_message,
    read_character,
    read_characters,
    read_characters_for_player,
    read_creature,
    read_creatures,
    read_player,
    read_players,
    read_room,
    read_room_enemies,
    read_room_enemy,
    read_room_members,
    read_room_messages,
    read_rooms,
    read_technique,
    read_techniques_for_character,
    to_typed_creature_values,
    to_typed_technique_values,
    utc_now,
)
from seed import (
    CATALOG_SEED,
    export_characters_csv,
    export_snapshot,
    load_snapshot_if_needed,
    migrate_csv_if_needed,
    seed_creature_catalog,
    to_typed_values,
)

from rules import (
    CLANS,
    HABITATS,
    HOUSES,
    TRAITS,
    RANK_AP_THRESHOLDS,
    clean_character,
    MAX_DICE,
    RANK_DICE,
    RANK_ORDER,
    SKILLS,
    compute_derived_fields,
    generate_creature_stats,
    rank_for_threat,
    roll_and_keep,
    roll_dice,
)





app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=config.load_session_secret())





def start():
    """Bring the database up: restore a backup if it is empty, then migrate.

    The order is the point. A deploy starts from an empty disk, so restoring first puts the
    backup's rows in at the schema they were exported from, and the migrations that follow
    transform them like any other existing data. Migrating first would build the newest
    schema empty and leave the restore to drop old-format rows straight into it.
    """
    enable_wal()
    restored = load_snapshot_if_needed()
    run_migrations()
    if not restored:
        migrate_csv_if_needed()
    seed_creature_catalog()


start()


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Render errors as a styled page.

    The default handler returns JSON, which a browser in dark mode paints as white text on
    a black background - the "blackscreen saying not found" people were running into.
    """
    titles = {400: "Bad Request", 403: "Not Permitted", 404: "Not Found", 405: "Not Allowed"}
    title = titles.get(exc.status_code, f"Error {exc.status_code}")
    detail = exc.detail if isinstance(exc.detail, str) else "Something went wrong."
    return HTMLResponse(
        content=render_error_page(request, title, detail),
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


@app.get("/export/characters.csv")
def export_csv(request: Request, token: str = ""):
    if not export_token_is_valid(token) and get_current_player(request) is None:
        return RedirectResponse(url="/login", status_code=303)
    export_characters_csv()
    return Response(
        content=config.CSV_FILE.read_text() if config.CSV_FILE.exists() else "",
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=characters.csv"},
    )


@app.get("/export/snapshot.json")
def export_snapshot_route(request: Request, token: str = ""):
    if not export_token_is_valid(token) and get_current_player(request) is None:
        return RedirectResponse(url="/login", status_code=303)
    return Response(
        content=export_snapshot(),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=seed.json"},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """A malformed path or form value should read as a page, not as raw JSON."""
    return HTMLResponse(
        content=render_error_page(request, "Bad Request", "That address or form value was not valid."),
        status_code=400,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Last resort.

    Starlette's default 500 is plain text, which a browser in dark mode paints as white on
    black - the same blackscreen the JSON 404 used to cause. Anything unexpected should
    still look like Nova and offer a way back.
    """
    return HTMLResponse(
        content=render_error_page(
            request, "Something went wrong",
            "That request could not be completed. The Headmaster has been notified.",
        ),
        status_code=500,
    )


@app.get("/favicon.ico")
def favicon():
    # Browsers request this on every page load; answer it rather than logging a 404 each time.
    return Response(status_code=204)


@app.get("/style.css")
def style():
    return Response(content=config.STYLE_FILE.read_text(), media_type="text/css")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return page(request, "home.html")


@app.get("/characters/new", response_class=HTMLResponse)
def new_character_form(request: Request):
    if get_current_player(request) is None:
        return RedirectResponse(url="/login", status_code=303)
    return page(request, "character_new.html", ranks=RANK_ORDER, thresholds=RANK_AP_THRESHOLDS,
                clans=CLANS, houses=HOUSES, traits=TRAITS)


@app.get("/characters", response_class=HTMLResponse)
def character_list(request: Request):
    rows = "".join(render_character_row(c, True) for c in read_characters())
    return page(request, "characters.html", rows=safe(rows), headers=CHARACTER_HEADERS)


@app.get("/players", response_class=HTMLResponse)
def player_list(request: Request):
    return page(request, "players.html", players=read_players())


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return page(request, "login.html", players=read_players())


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    request.session["player_id"] = int(form["player_id"])
    return RedirectResponse(url="/", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.post("/enroll")
async def enroll(request: Request):
    form = await request.form()
    conn = get_connection()
    try:
        wants_hm = "is_hm" in form
        hm_exists = conn.execute("SELECT COUNT(*) FROM players WHERE is_hm = 1").fetchone()[0] > 0
        is_hm = 1 if (wants_hm and not hm_exists) else 0
        cursor = conn.execute("INSERT INTO players (name, is_hm) VALUES (?, ?)", (form["name"], is_hm))
        conn.commit()
        player_id = cursor.lastrowid
    finally:
        conn.close()
    request.session["player_id"] = player_id
    export_characters_csv()
    return RedirectResponse(url="/", status_code=303)


@app.get("/player/{id}", response_class=HTMLResponse)
def player_profile(id: int, request: Request):
    player = read_player(id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    rows = "".join(render_character_row(c, False) for c in read_characters_for_player(id))
    return page(request, "player_profile.html", name=player["name"], rows=safe(rows),
                headers=CHARACTER_HEADERS)


@app.get("/character/{id}/techniques", response_class=HTMLResponse)
def technique_list(id: int, request: Request):
    character = read_character(id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    rows = "".join(render_technique_row(t) for t in read_techniques_for_character(id))
    add_link = (
        f"<p><a href='/character/{id}/techniques/new'>Add Technique</a></p>"
        if can_edit_character(request, character) else ""
    )
    return page(request, "techniques.html", character_name=character["name"], id=id,
                rows=safe(rows), add_link=safe(add_link))


@app.get("/character/{id}/techniques/new", response_class=HTMLResponse)
def new_technique_form(id: int, request: Request):
    character = read_character(id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    return page(request, "technique_new.html", id=id, character_name=character["name"])


@app.post("/character/{id}/techniques")
async def create_technique(id: int, request: Request):
    character = read_character(id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    form = await request.form()
    values = to_typed_technique_values(form)
    conn = get_connection()
    try:
        conn.execute(
            f"INSERT INTO techniques (character_id, {', '.join(TECHNIQUE_FIELDS)}) "
            f"VALUES (?, {', '.join('?' for _ in TECHNIQUE_FIELDS)})",
            [id] + values,
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url=f"/character/{id}/techniques", status_code=303)


@app.get("/technique/{id}/edit", response_class=HTMLResponse)
def edit_technique_form(id: int, request: Request):
    technique = read_technique(id)
    if technique is None:
        raise HTTPException(status_code=404, detail="Technique not found")
    character = read_character(technique["character_id"])
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    return page(request, "technique_edit.html", id=id, character_id=character["id"],
                character_name=character["name"],
                **{f: technique[f] for f in TECHNIQUE_FIELDS})


@app.post("/technique/{id}/edit")
async def edit_technique(id: int, request: Request):
    technique = read_technique(id)
    if technique is None:
        raise HTTPException(status_code=404, detail="Technique not found")
    character = read_character(technique["character_id"])
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    form = await request.form()
    values = to_typed_technique_values(form)
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE techniques SET {', '.join(f'{f} = ?' for f in TECHNIQUE_FIELDS)} WHERE id = ?",
            values + [id],
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url=f"/character/{character['id']}/techniques", status_code=303)


@app.post("/technique/{id}/delete")
async def delete_technique(id: int, request: Request):
    technique = read_technique(id)
    if technique is None:
        raise HTTPException(status_code=404, detail="Technique not found")
    character = read_character(technique["character_id"])
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    conn = get_connection()
    try:
        conn.execute("DELETE FROM techniques WHERE id = ?", (id,))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url=f"/character/{character['id']}/techniques", status_code=303)


@app.get("/character/{id}/edit", response_class=HTMLResponse)
def edit_character_form(id: int, request: Request):
    character = read_character(id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    if current_player["is_hm"]:
        options = render_player_options(read_players(), selected_id=character["player_id"])
        player_field = f"<label>Player: <select name='player_id' required>{options}</select></label><br />"
    else:
        player_field = ""
    return page(request, "edit.html", id=id, player_field=safe(player_field),
                ranks=RANK_ORDER, clans=CLANS, houses=HOUSES, traits=TRAITS,
                **{f: character[f] for f in FIELDS})


@app.post("/character/{id}/edit")
async def edit_character(id: int, request: Request):
    character = read_character(id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    form = await request.form()
    updated = clean_character(form, existing=character)
    values = [updated[f] for f in FIELDS]
    if current_player["is_hm"] and "player_id" in form:
        player_id = int(form["player_id"])
    else:
        player_id = character["player_id"]
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE characters SET player_id = ?, {', '.join(f'{f} = ?' for f in FIELDS)} WHERE id = ?",
            [player_id] + values + [id],
        )
        conn.commit()
    finally:
        conn.close()
    export_characters_csv()
    return RedirectResponse(url="/characters", status_code=303)


@app.post("/character/{id}/delete")
async def delete_character(id: int, request: Request):
    character = read_character(id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    conn = get_connection()
    try:
        conn.execute("DELETE FROM techniques WHERE character_id = ?", (id,))
        conn.execute("DELETE FROM characters WHERE id = ?", (id,))
        conn.commit()
    finally:
        conn.close()
    export_characters_csv()
    return RedirectResponse(url="/characters", status_code=303)


@app.post("/character")
async def create_character(request: Request):
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    character = clean_character(form)
    values = [character[f] for f in FIELDS]
    conn = get_connection()
    try:
        columns = ["player_id"] + FIELDS
        conn.execute(
            f"INSERT INTO characters ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            [current_player["id"]] + values,
        )
        conn.commit()
    finally:
        conn.close()
    export_characters_csv()
    return RedirectResponse(url="/characters", status_code=303)


@app.get("/enemies", response_class=HTMLResponse)
def enemy_list(request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    rows = "".join(render_creature_row(c) for c in read_creatures())
    return page(request, "enemies.html", rows=safe(rows))


@app.get("/enemies/new", response_class=HTMLResponse)
def new_enemy_form(request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    return page(request, "enemy_new.html", habitats=HABITATS, skills=SKILLS)


@app.post("/enemy")
async def create_enemy(request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    form = await request.form()
    values = to_typed_creature_values(form)
    conn = get_connection()
    try:
        conn.execute(
            f"INSERT INTO creatures ({', '.join(CREATURE_FIELDS)}) VALUES ({', '.join('?' for _ in CREATURE_FIELDS)})",
            values,
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/enemies", status_code=303)


@app.get("/enemy/{id}/edit", response_class=HTMLResponse)
def edit_enemy_form(id: int, request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    creature = read_creature(id)
    if creature is None:
        raise HTTPException(status_code=404, detail="Creature not found")
    return page(request, "enemy_edit.html", id=id, habitats=HABITATS, skills=SKILLS,
                selected_habitat=creature["habitat"], selected_skill=creature["main_skill"],
                **{f: creature[f] for f in CREATURE_FIELDS})


@app.post("/enemy/{id}/edit")
async def edit_enemy(id: int, request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    form = await request.form()
    values = to_typed_creature_values(form)
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE creatures SET {', '.join(f'{f} = ?' for f in CREATURE_FIELDS)} WHERE id = ?",
            values + [id],
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/enemies", status_code=303)


@app.post("/enemy/{id}/delete")
async def delete_enemy(id: int, request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    conn = get_connection()
    try:
        conn.execute("DELETE FROM creatures WHERE id = ?", (id,))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/enemies", status_code=303)


@app.post("/enemy/{id}/generate", response_class=HTMLResponse)
async def generate_enemy(id: int, request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    creature = read_creature(id)
    if creature is None:
        raise HTTPException(status_code=404, detail="Creature not found")
    form = await request.form()
    try:
        threat_level = int(form.get("threat_level", creature["default_threat_level"]))
    except (TypeError, ValueError):
        threat_level = creature["default_threat_level"]
    threat_level = max(1, min(6, threat_level))
    stats, talent_uses, talent_cooldown = generate_creature_stats(creature, threat_level)
    return page(request, "enemy_generated.html", name=creature["name"], threat_level=threat_level,
                stats=stats, talent_name=creature["talent_name"],
                talent_effect=creature["talent_effect"], talent_uses=talent_uses,
                talent_cooldown=talent_cooldown, drops=creature["drops"])


@app.get("/play", response_class=HTMLResponse)
def play_index(request: Request):
    current_player = get_current_player(request)
    rooms = read_rooms()
    if rooms:
        # Open rooms first; closed ones stay listed so their logs remain reachable.
        rooms.sort(key=lambda r: (bool(r["closed_at"]), -r["id"]))
        rows = "".join(
            f"<tr><td><a href='/play/room/{r['id']}'>{esc(r['name'])}</a></td>"
            f"<td>{esc(r['description'])}</td><td>{esc(r['creator_name'])}</td>"
            f"<td>{r['member_count']}</td><td>{esc(format_stamp(r['created_at']))}</td>"
            f"<td>{'Closed' if r['closed_at'] else 'Open'}</td></tr>"
            for r in rooms
        )
        table = (
            "<div class='table-wrap'><table>"
            "<tr><th>Room</th><th>About</th><th>Opened by</th>"
            f"<th>Characters</th><th>Opened</th><th>Status</th></tr>{rows}</table></div>"
        )
    else:
        table = "<p class='quotes'>No rooms are open. Start one below.</p>"
    if current_player:
        create_form = (
            "<h2>Open a room</h2>"
            "<form class='control-row' method='post' action='/play/rooms'>"
            "<label>Name: <input type='text' name='name' required maxlength='80' /></label>"
            "<label>About: <input type='text' name='description' maxlength='200' /></label>"
            "<button type='submit'>Open</button></form>"
        )
    else:
        create_form = "<p class='quotes'><a href='/login' class='section-link'>Log in to open a room.</a></p>"
    return page(request, "play.html", rooms=safe(table), create_form=safe(create_form))


@app.post("/play/rooms")
async def create_room(request: Request):
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    name = (form.get("name") or "").strip()[:80]
    if not name:
        return RedirectResponse(url="/play", status_code=303)
    description = (form.get("description") or "").strip()[:200]
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO rooms (name, description, created_by, created_at) VALUES (?, ?, ?, ?)",
            (name, description, current_player["id"], utc_now()),
        )
        conn.commit()
        room_id = cursor.lastrowid
    finally:
        conn.close()
    return RedirectResponse(url=f"/play/room/{room_id}", status_code=303)


@app.get("/play/room/{id}", response_class=HTMLResponse)
def room_view(id: int, request: Request):
    room = read_room(id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    current_player = get_current_player(request)
    members = read_room_members(id)
    member_rows = "".join(
        f"<tr><td>{esc(m['name'])}</td><td>{esc(m['player_name'])}</td>"
        f"<td>{esc(m['rank'])}</td><td>{esc(m['trait'])}</td></tr>"
        for m in members
    ) or "<tr><td colspan='4'>Nobody has joined yet.</td></tr>"

    enemies = read_room_enemies(id)
    is_hm = bool(current_player and current_player["is_hm"])
    enemy_panel = render_enemy_panel(id, enemies, is_hm, bool(room["closed_at"]))

    is_closed = bool(room["closed_at"])
    if can_close_room(room, current_player):
        if is_closed:
            manage = (
                f"<form class='control-row' method='post' action='/play/room/{id}/reopen'>"
                "<button type='submit'>Reopen room</button></form>"
            )
        else:
            manage = (
                f"<form class='control-row' method='post' action='/play/room/{id}/close' "
                "onsubmit=\"return confirm('Close this room? The log is kept and it can be reopened.')\">"
                "<button type='submit'>Close room</button></form>"
            )
    else:
        manage = ""

    mine = character_in_room(id, current_player["id"]) if current_player else None
    if is_closed:
        note = f"<p class='quotes'>This room was closed {esc(format_stamp(room['closed_at']))}. "
        note += "The log is kept, but nothing new can be posted.</p>"
        if mine:
            note += (
                f"<form class='control-row' method='post' action='/play/room/{id}/leave' "
                "onsubmit=\"return confirm('Leave this room?')\">"
                "<button type='submit'>Leave room</button></form>"
            )
        controls = note + manage
    elif mine:
        roll_count, keep_count = RANK_DICE.get(str(mine["rank"]).strip().title(), (1, 1))
        controls = (
            f"<p>You are in this room as <strong>{esc(mine['name'])}</strong> "
            f"({esc(mine['rank'])} &mdash; {roll_count}d6 keep {keep_count}).</p>"
            f"<form class='control-row' method='post' action='/play/room/{id}/message'>"
            "<label>Say: <input type='text' name='body' required maxlength='500' autocomplete='off' /></label>"
            "<button type='submit'>Send</button></form>"
            f"<form class='control-row' method='post' action='/play/room/{id}/roll'>"
            "<label>Roll: <select name='mode'>"
            f"<option value='rank'>My rank ({roll_count}d6 keep {keep_count})</option>"
            "<option value='d20'>1d20 (Possibility)</option>"
            "<option value='custom'>Custom</option></select></label>"
            f"<label>Custom roll: <input type='number' name='roll_count' min='1' max='{MAX_DICE}' value='{roll_count}' /></label>"
            f"<label>Keep: <input type='number' name='keep_count' min='1' max='{MAX_DICE}' value='{keep_count}' /></label>"
            "<button type='submit'>Roll</button></form>"
            f"<form class='control-row' method='post' action='/play/room/{id}/leave' "
            "onsubmit=\"return confirm('Leave this room?')\">"
            "<button type='submit'>Leave room</button></form>"
        )
    elif current_player:
        available = [
            c for c in read_characters_for_player(current_player["id"])
            if not any(m["id"] == c["id"] for m in members)
        ]
        if available:
            options = "".join(f"<option value='{c['id']}'>{esc(c['name'])}</option>" for c in available)
            controls = (
                f"<form class='control-row' method='post' action='/play/room/{id}/join'>"
                f"<label>Join as: <select name='character_id' required>{options}</select></label>"
                "<button type='submit'>Join</button></form>"
            )
        else:
            controls = (
                "<p class='quotes'>You have no characters yet. "
                "<a href='/characters/new' class='section-link'>Create one</a> to join.</p>"
            )
    else:
        controls = "<p class='quotes'><a href='/login' class='section-link'>Log in to join this room.</a></p>"
    if not is_closed:
        controls += manage

    return page(request, "room.html", id=id, room_name=room["name"],
                room_description=room["description"], member_rows=safe(member_rows),
                enemy_panel=safe(enemy_panel), controls=safe(controls),
                messages=safe(render_room_messages(read_room_messages(id))))


@app.get("/play/room/{id}/messages", response_class=HTMLResponse)
def room_messages_fragment(id: int):
    """Message log on its own, so the room page can poll for new activity."""
    if read_room(id) is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return render_room_messages(read_room_messages(id))


@app.post("/play/room/{id}/enemy")
async def spawn_room_enemy(id: int, request: Request):
    _room, current_player = require_room_hm(id, request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    try:
        creature_id = int(form["creature_id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Pick a creature to generate.")
    creature = read_creature(creature_id)
    if creature is None:
        raise HTTPException(status_code=404, detail="Creature not found")
    try:
        threat_level = int(form.get("threat_level", creature["default_threat_level"]))
    except (TypeError, ValueError):
        threat_level = creature["default_threat_level"]
    threat_level = max(1, min(6, threat_level))

    stats, talent_uses, talent_cooldown = generate_creature_stats(creature, threat_level)
    # Several of the same creature can be in play at once, so number them per room.
    existing = [e for e in read_room_enemies(id, include_dismissed=True)
                if e["creature_id"] == creature_id]
    name = creature["name"] if not existing else f"{creature['name']} {len(existing) + 1}"

    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO room_enemies (room_id, creature_id, name, threat_level, stats, "
            "talent_name, talent_effect, talent_uses, talent_cooldown, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (id, creature_id, name, threat_level, json.dumps(stats), creature["talent_name"],
             creature["talent_effect"], talent_uses, talent_cooldown, utc_now()),
        )
        conn.commit()
        enemy_id = cursor.lastrowid
    finally:
        conn.close()

    summary = ", ".join(f"{skill} {value}" for skill, value in stats.items())
    post_room_message(
        id, None, "system",
        f"{current_player['name']} sent in {name} ({rank_for_threat(threat_level)}, "
        f"threat {threat_level}) - {summary}.",
    )
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/enemy/{enemy_id}/roll")
async def roll_as_enemy(id: int, enemy_id: int, request: Request):
    _room, current_player = require_room_hm(id, request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    enemy = read_room_enemy(enemy_id)
    if enemy is None or enemy["room_id"] != id or enemy["dismissed_at"]:
        raise HTTPException(status_code=404, detail="Enemy not found in this room")
    form = await request.form()
    mode = form.get("mode", "threat")
    if mode == "d20":
        body = f"rolls <strong>1d20</strong>: <strong>{roll_dice(1, 20)[0]}</strong>"
    else:
        if mode == "threat":
            roll_count, keep_count = RANK_DICE[rank_for_threat(enemy["threat_level"])]
        else:
            try:
                roll_count = int(form.get("roll_count", 1))
                keep_count = int(form.get("keep_count", 1))
            except (TypeError, ValueError):
                roll_count, keep_count = 1, 1
        roll_count = max(1, min(roll_count, MAX_DICE))
        keep_count = max(1, min(keep_count, roll_count))
        all_rolls, kept_sum = roll_and_keep(roll_count, keep_count)
        body = (
            f"rolls <strong>{roll_count}d6 keep {keep_count}</strong>: "
            f"{render_dice_result(all_rolls, keep_count)}&rarr; <strong>{kept_sum}</strong>"
        )
    post_room_message(id, None, "roll", body, enemy_id=enemy_id)
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/enemy/{enemy_id}/dismiss")
async def dismiss_room_enemy(id: int, enemy_id: int, request: Request):
    _room, current_player = require_room_hm(id, request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    enemy = read_room_enemy(enemy_id)
    if enemy is None or enemy["room_id"] != id:
        raise HTTPException(status_code=404, detail="Enemy not found in this room")
    if not enemy["dismissed_at"]:
        conn = get_connection()
        try:
            conn.execute("UPDATE room_enemies SET dismissed_at = ? WHERE id = ?", (utc_now(), enemy_id))
            conn.commit()
        finally:
            conn.close()
        post_room_message(id, None, "system", f"{enemy['name']} left the field.")
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/close")
async def close_room(id: int, request: Request):
    room = read_room(id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    if not can_close_room(room, current_player):
        raise HTTPException(status_code=403, detail="Only whoever opened this room can close it.")
    if not room["closed_at"]:
        conn = get_connection()
        try:
            conn.execute("UPDATE rooms SET closed_at = ? WHERE id = ?", (utc_now(), id))
            conn.commit()
        finally:
            conn.close()
        post_room_message(id, None, "system", f"{current_player['name']} closed the room.")
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/reopen")
async def reopen_room(id: int, request: Request):
    room = read_room(id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    if not can_close_room(room, current_player):
        raise HTTPException(status_code=403, detail="Only whoever opened this room can reopen it.")
    if room["closed_at"]:
        conn = get_connection()
        try:
            conn.execute("UPDATE rooms SET closed_at = NULL WHERE id = ?", (id,))
            conn.commit()
        finally:
            conn.close()
        post_room_message(id, None, "system", f"{current_player['name']} reopened the room.")
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/join")
async def join_room(id: int, request: Request):
    room = read_room(id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    if room["closed_at"]:
        raise HTTPException(status_code=403, detail="This room is closed.")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    try:
        character_id = int(form["character_id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Pick a character to join as")
    character = read_character(character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    if character["player_id"] != current_player["id"] and not current_player["is_hm"]:
        raise HTTPException(status_code=403, detail="That is not your character")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO room_members (room_id, character_id, joined_at) VALUES (?, ?, ?)",
            (id, character_id, utc_now()),
        )
        conn.commit()
    finally:
        conn.close()
    post_room_message(id, character_id, "system", f"{character['name']} entered the room.")
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/leave")
async def leave_room(id: int, request: Request):
    # Leaving stays available after a room closes; only new activity is blocked.
    _room, character = require_room_membership(id, request, allow_closed=True)
    if character is None:
        return RedirectResponse(url="/login", status_code=303)
    conn = get_connection()
    try:
        conn.execute("DELETE FROM room_members WHERE room_id = ? AND character_id = ?", (id, character["id"]))
        conn.commit()
    finally:
        conn.close()
    post_room_message(id, character["id"], "system", f"{character['name']} left the room.")
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/message")
async def send_room_message(id: int, request: Request):
    _room, character = require_room_membership(id, request)
    if character is None:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    body = (form.get("body") or "").strip()[:500]
    if body:
        post_room_message(id, character["id"], "text", body)
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


@app.post("/play/room/{id}/roll")
async def roll_in_room(id: int, request: Request):
    _room, character = require_room_membership(id, request)
    if character is None:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    mode = form.get("mode", "rank")
    if mode == "d20":
        result = roll_dice(1, 20)[0]
        body = f"rolls <strong>1d20</strong>: <strong>{result}</strong>"
    else:
        if mode == "rank":
            roll_count, keep_count = RANK_DICE.get(str(character["rank"]).strip().title(), (1, 1))
        else:
            try:
                roll_count = int(form.get("roll_count", 1))
                keep_count = int(form.get("keep_count", 1))
            except (TypeError, ValueError):
                roll_count, keep_count = 1, 1
        roll_count = max(1, min(roll_count, MAX_DICE))
        keep_count = max(1, min(keep_count, roll_count))
        all_rolls, kept_sum = roll_and_keep(roll_count, keep_count)
        body = (
            f"rolls <strong>{roll_count}d6 keep {keep_count}</strong>: "
            f"{render_dice_result(all_rolls, keep_count)}&rarr; <strong>{kept_sum}</strong>"
        )
    post_room_message(id, character["id"], "roll", body)
    return RedirectResponse(url=f"/play/room/{id}", status_code=303)


# Run the app with uvicorn when this file is executed directly.
def main():
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)


if __name__ == "__main__":
    main()
