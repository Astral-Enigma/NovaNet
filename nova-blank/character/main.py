# Character creator FastAPI app.
# Allows creating characters with any fields defined in FIELDS, saved to a SQLite database.
# Install dependencies on Ubuntu:
#   sudo apt update && sudo apt install -y python3-pip
#   pip3 install fastapi uvicorn python-multipart
# Run:
#   uv run --with fastapi --with uvicorn --with python-multipart --with itsdangerous python3 main.py

import csv
import json
import math
import os
import random
import secrets
import sqlite3
from html import escape
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware

# Hosts like Render give each deploy a fresh, empty filesystem, so anything written next to
# this file is wiped every time the app ships. NOVANET_DATA_DIR points the database and the
# session secret at a persistent disk instead; it defaults to alongside the code so local
# development is unchanged.
DATA_DIR = Path(os.environ.get("NOVANET_DATA_DIR", Path(__file__).parent))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SECRET_KEY_FILE = DATA_DIR / "session_secret.txt"


def load_session_secret():
    # A freshly generated secret on every start would log every user out on restart, so
    # prefer the environment and fall back to a secret persisted next to the database.
    from_env = os.environ.get("NOVANET_SECRET_KEY")
    if from_env:
        return from_env
    if SECRET_KEY_FILE.exists():
        stored = SECRET_KEY_FILE.read_text().strip()
        if stored:
            return stored
    generated = secrets.token_hex(32)
    SECRET_KEY_FILE.write_text(generated)
    SECRET_KEY_FILE.chmod(0o600)
    return generated


app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=load_session_secret())

CSV_FILE = Path(__file__).parent / "characters.csv"
DB_FILE = DATA_DIR / "characters.db"
HOME_FILE = Path(__file__).parent / "home.html"
CHARACTER_NEW_FILE = Path(__file__).parent / "character_new.html"
LIST_FILE = Path(__file__).parent / "characters.html"
EDIT_FILE = Path(__file__).parent / "edit.html"
PLAYERS_FILE = Path(__file__).parent / "players.html"
PLAYER_PROFILE_FILE = Path(__file__).parent / "player_profile.html"
LOGIN_FILE = Path(__file__).parent / "login.html"
TECHNIQUES_FILE = Path(__file__).parent / "techniques.html"
TECHNIQUE_NEW_FILE = Path(__file__).parent / "technique_new.html"
TECHNIQUE_EDIT_FILE = Path(__file__).parent / "technique_edit.html"
ENEMIES_FILE = Path(__file__).parent / "enemies.html"
ENEMY_NEW_FILE = Path(__file__).parent / "enemy_new.html"
ENEMY_EDIT_FILE = Path(__file__).parent / "enemy_edit.html"
ENEMY_GENERATED_FILE = Path(__file__).parent / "enemy_generated.html"
DICE_FILE = Path(__file__).parent / "dice.html"
STYLE_FILE = Path(__file__).parent / "style.css"
FIELDS = ["name", "age", "rank", "clan", "house", "trait", "trauma", "pneuma", "deftness", "handling", "tenacity", "wit", "perception", "composure", "pluck", "potential",]
NUMERIC_FIELDS = ["age", "trauma", "pneuma", "deftness", "handling", "tenacity", "wit", "perception", "composure", "pluck", "potential"]
TECHNIQUE_FIELDS = ["name", "description", "toll", "type", "category", "effect", "burst", "duration"]
CREATURE_FIELDS = ["name", "description", "habitat", "main_skill", "default_threat_level", "talent_name", "talent_effect", "drops"]
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


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                is_hm INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER NOT NULL REFERENCES players(id),
                name TEXT NOT NULL,
                age INTEGER NOT NULL,
                rank TEXT NOT NULL,
                clan TEXT NOT NULL,
                house TEXT NOT NULL,
                trait TEXT NOT NULL,
                trauma INTEGER NOT NULL,
                pneuma INTEGER NOT NULL,
                deftness INTEGER NOT NULL,
                handling INTEGER NOT NULL,
                tenacity INTEGER NOT NULL,
                wit INTEGER NOT NULL,
                perception INTEGER NOT NULL,
                composure INTEGER NOT NULL,
                pluck INTEGER NOT NULL DEFAULT 0,
                potential INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS techniques (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL REFERENCES characters(id),
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                toll INTEGER NOT NULL,
                type TEXT NOT NULL,
                category TEXT NOT NULL,
                effect TEXT NOT NULL,
                burst TEXT NOT NULL DEFAULT '',
                duration TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS creatures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                habitat TEXT NOT NULL,
                main_skill TEXT NOT NULL,
                default_threat_level INTEGER NOT NULL,
                talent_name TEXT NOT NULL,
                talent_effect TEXT NOT NULL,
                drops TEXT NOT NULL
            )
            """
        )
        conn.commit()
        migrate_player_id_if_needed(conn)
        migrate_is_hm_if_needed(conn)
    finally:
        conn.close()


def migrate_player_id_if_needed(conn):
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(characters)")]
    if "player_id" in columns:
        return
    conn.execute("ALTER TABLE characters ADD COLUMN player_id INTEGER")
    unassigned_id = get_or_create_unassigned_player(conn)
    conn.execute("UPDATE characters SET player_id = ? WHERE player_id IS NULL", (unassigned_id,))
    conn.commit()


def migrate_is_hm_if_needed(conn):
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(players)")]
    if "is_hm" in columns:
        return
    conn.execute("ALTER TABLE players ADD COLUMN is_hm INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def get_or_create_unassigned_player(conn):
    row = conn.execute("SELECT id FROM players WHERE name = 'Unassigned'").fetchone()
    if row:
        return row["id"]
    cursor = conn.execute("INSERT INTO players (name) VALUES ('Unassigned')")
    conn.commit()
    return cursor.lastrowid


def migrate_csv_if_needed():
    if not CSV_FILE.exists():
        return
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0]
        if count > 0:
            return
        with open(CSV_FILE, newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return
        unassigned_id = get_or_create_unassigned_player(conn)
        for row in rows:
            values = to_typed_values(row)
            conn.execute(
                f"INSERT INTO characters (player_id, {', '.join(FIELDS)}) "
                f"VALUES (?, {', '.join('?' for _ in FIELDS)})",
                [unassigned_id] + values,
            )
        conn.commit()
    finally:
        conn.close()


def to_typed_values(character):
    values = []
    for f in FIELDS:
        raw = character.get(f, "0")
        if f in NUMERIC_FIELDS:
            try:
                values.append(int(raw))
            except (TypeError, ValueError):
                values.append(0)
        else:
            values.append(raw)
    return values


init_db()
migrate_csv_if_needed()


def read_characters():
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT characters.*, players.name AS player_name FROM characters "
            "JOIN players ON characters.player_id = players.id ORDER BY characters.id"
        )]
    finally:
        conn.close()


def read_character(id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT characters.*, players.name AS player_name FROM characters "
            "JOIN players ON characters.player_id = players.id WHERE characters.id = ?",
            (id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def read_characters_for_player(player_id):
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM characters WHERE player_id = ? ORDER BY id", (player_id,)
        )]
    finally:
        conn.close()


def read_techniques_for_character(character_id):
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM techniques WHERE character_id = ? ORDER BY id", (character_id,)
        )]
    finally:
        conn.close()


def read_technique(id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM techniques WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def to_typed_technique_values(form):
    values = []
    for f in TECHNIQUE_FIELDS:
        raw = form.get(f, "")
        if f == "toll":
            try:
                values.append(int(raw))
            except (TypeError, ValueError):
                values.append(0)
        else:
            values.append(raw)
    return values


def render_technique_row(t):
    return (
        "<tr>" + "".join(f"<td>{esc(t[f])}</td>" for f in TECHNIQUE_FIELDS) +
        f"<td><a href='/technique/{t['id']}/edit'>Edit</a></td>"
        f"<td><form method='post' action='/technique/{t['id']}/delete' style='display:inline' "
        f"onsubmit=\"return confirm({js_string('Delete ' + str(t['name']) + '?')})\">"
        f"<button type='submit'>Delete</button></form></td></tr>"
    )


def read_creatures():
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM creatures ORDER BY id")]
    finally:
        conn.close()


def read_creature(id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM creatures WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def to_typed_creature_values(form):
    values = []
    for f in CREATURE_FIELDS:
        raw = form.get(f, "")
        if f == "default_threat_level":
            try:
                values.append(int(raw))
            except (TypeError, ValueError):
                values.append(1)
        else:
            values.append(raw)
    return values


def render_creature_row(c):
    return (
        "<tr>" + "".join(f"<td>{esc(c[f])}</td>" for f in CREATURE_FIELDS) +
        f"<td><form method='post' action='/enemy/{c['id']}/generate' style='display:inline'>"
        f"<input type='number' name='threat_level' value='{c['default_threat_level']}' min='1' max='6' style='width:3em' />"
        f"<button type='submit'>Generate</button></form></td>"
        f"<td><a href='/enemy/{c['id']}/edit'>Edit</a></td>"
        f"<td><form method='post' action='/enemy/{c['id']}/delete' style='display:inline' "
        f"onsubmit=\"return confirm({js_string('Delete ' + str(c['name']) + '?')})\">"
        f"<button type='submit'>Delete</button></form></td></tr>"
    )


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


def require_hm_login(request):
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    if not current_player["is_hm"]:
        raise HTTPException(status_code=403, detail="HM access required")
    return None


def read_players():
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM players ORDER BY id")]
    finally:
        conn.close()


def read_player(id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM players WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_current_player(request):
    player_id = request.session.get("player_id")
    return read_player(player_id) if player_id else None


def render_nav(request):
    current_player = get_current_player(request)
    links = [
        ("Home", "/"),
        ("Create a Character", "/characters/new"),
        ("Characters", "/characters"),
        ("Players", "/players"),
        ("Dice", "/dice"),
    ]
    if current_player and current_player["is_hm"]:
        links.append(("Enemies", "/enemies"))
    links.append(("Play", "#"))
    links.append(("Nova News Network", "#"))
    items = "".join(f"<li class='site-section'><a href='{href}' class='section-link'>{label}</a></li>" for label, href in links)
    if current_player:
        role = "HM" if current_player["is_hm"] else "Student"
        auth = (
            f"<li class='site-section'>Logged in as {esc(current_player['name'])} ({role})</li>"
            "<li class='site-section'><form method='post' action='/logout' style='display:inline'>"
            "<button type='submit' class='section-link'>Logout</button></form></li>"
        )
    else:
        auth = "<li class='site-section'><a href='/login' class='section-link'>Login</a></li>"
    return f"<ul class='nav-links'>{items}{auth}</ul>"


def esc(value):
    """Escape a value for interpolation into HTML text or a quoted attribute."""
    return escape("" if value is None else str(value), quote=True)


def js_string(value):
    """Escape a value as a JS string literal safe inside a double-quoted HTML attribute.

    HTML-escaping alone is not enough here: the parser decodes entities inside the
    attribute before the JavaScript is parsed, so an apostrophe would still break out of
    the string. json.dumps produces a properly escaped literal first.
    """
    return escape(json.dumps("" if value is None else str(value)), quote=True)


def render_character_row(c, show_player):
    player_cell = f"<td>{esc(c['player_name'])}</td>" if show_player else ""
    return (
        "<tr>" + player_cell + "".join(f"<td>{esc(c[f])}</td>" for f in FIELDS) +
        f"<td><a href='/character/{c['id']}/techniques'>Techniques</a></td>"
        f"<td><a href='/character/{c['id']}/edit'>Edit</a></td>"
        f"<td><form method='post' action='/character/{c['id']}/delete' style='display:inline' "
        f"onsubmit=\"return confirm({js_string('Delete ' + str(c['name']) + '?')})\">"
        f"<button type='submit'>Delete</button></form></td></tr>"
    )


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


def render_player_options(players, selected_id=None):
    return "".join(
        f"<option value='{p['id']}'{' selected' if p['id'] == selected_id else ''}>{esc(p['name'])}</option>"
        for p in players
    )


@app.get("/style.css")
def style():
    return Response(content=STYLE_FILE.read_text(), media_type="text/css")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    nav = render_nav(request)
    return HOME_FILE.read_text().replace("{{ nav }}", nav)


@app.get("/characters/new", response_class=HTMLResponse)
def new_character_form(request: Request):
    if get_current_player(request) is None:
        return RedirectResponse(url="/login", status_code=303)
    nav = render_nav(request)
    return CHARACTER_NEW_FILE.read_text().replace("{{ nav }}", nav)


@app.get("/characters", response_class=HTMLResponse)
def character_list(request: Request):
    rows = "".join(render_character_row(c, True) for c in read_characters())
    nav = render_nav(request)
    return LIST_FILE.read_text().replace("{{ rows }}", rows).replace("{{ nav }}", nav)


@app.get("/players", response_class=HTMLResponse)
def player_list(request: Request):
    rows = "".join(f"<tr><td><a href='/player/{p['id']}'>{esc(p['name'])}</a></td></tr>" for p in read_players())
    nav = render_nav(request)
    return PLAYERS_FILE.read_text().replace("{{ rows }}", rows).replace("{{ nav }}", nav)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    options = render_player_options(read_players())
    nav = render_nav(request)
    return LOGIN_FILE.read_text().replace("{{ player_options }}", options).replace("{{ nav }}", nav)


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
    return RedirectResponse(url="/", status_code=303)


@app.get("/player/{id}", response_class=HTMLResponse)
def player_profile(id: int, request: Request):
    player = read_player(id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    rows = "".join(render_character_row(c, False) for c in read_characters_for_player(id))
    nav = render_nav(request)
    return (
        PLAYER_PROFILE_FILE.read_text()
        .replace("{{ name }}", esc(player["name"]))
        .replace("{{ rows }}", rows)
        .replace("{{ nav }}", nav)
    )


def require_owner_or_hm(current_player, character):
    if current_player["id"] != character["player_id"] and not current_player["is_hm"]:
        raise HTTPException(status_code=403, detail="Not permitted to modify this character")


def can_edit_character(request, character):
    current_player = get_current_player(request)
    return current_player is not None and (
        current_player["id"] == character["player_id"] or current_player["is_hm"]
    )


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
    nav = render_nav(request)
    return (
        TECHNIQUES_FILE.read_text()
        .replace("{{ character_name }}", esc(character["name"]))
        .replace("{{ id }}", str(id))
        .replace("{{ rows }}", rows)
        .replace("{{ add_link }}", add_link)
        .replace("{{ nav }}", nav)
    )


@app.get("/character/{id}/techniques/new", response_class=HTMLResponse)
def new_technique_form(id: int, request: Request):
    character = read_character(id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    require_owner_or_hm(current_player, character)
    nav = render_nav(request)
    return (
        TECHNIQUE_NEW_FILE.read_text()
        .replace("{{ id }}", str(id))
        .replace("{{ character_name }}", esc(character["name"]))
        .replace("{{ nav }}", nav)
    )


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
    nav = render_nav(request)
    html = (
        TECHNIQUE_EDIT_FILE.read_text()
        .replace("{{ id }}", str(id))
        .replace("{{ character_id }}", str(character["id"]))
        .replace("{{ character_name }}", esc(character["name"]))
        .replace("{{ nav }}", nav)
    )
    for f in TECHNIQUE_FIELDS:
        html = html.replace(f"{{{{ {f} }}}}", esc(technique[f]))
    return html


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
    nav = render_nav(request)
    html = (
        EDIT_FILE.read_text()
        .replace("{{ id }}", str(id))
        .replace("{{ player_field }}", player_field)
        .replace("{{ nav }}", nav)
    )
    for f in FIELDS:
        html = html.replace(f"{{{{ {f} }}}}", esc(character[f]))
    return html


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
    updated = compute_derived_fields({f: form[f] for f in FIELDS})
    values = to_typed_values(updated)
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
    return RedirectResponse(url="/characters", status_code=303)


@app.post("/character")
async def create_character(request: Request):
    current_player = get_current_player(request)
    if current_player is None:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    character = compute_derived_fields({f: form[f] for f in FIELDS})
    values = to_typed_values(character)
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
    return RedirectResponse(url="/characters", status_code=303)


@app.get("/enemies", response_class=HTMLResponse)
def enemy_list(request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    rows = "".join(render_creature_row(c) for c in read_creatures())
    nav = render_nav(request)
    return ENEMIES_FILE.read_text().replace("{{ rows }}", rows).replace("{{ nav }}", nav)


@app.get("/enemies/new", response_class=HTMLResponse)
def new_enemy_form(request: Request):
    redirect = require_hm_login(request)
    if redirect:
        return redirect
    nav = render_nav(request)
    habitat_options = "".join(f"<option value='{h}'>{h}</option>" for h in HABITATS)
    skill_options = "".join(f"<option value='{s}'>{s}</option>" for s in SKILLS)
    return (
        ENEMY_NEW_FILE.read_text()
        .replace("{{ habitat_options }}", habitat_options)
        .replace("{{ skill_options }}", skill_options)
        .replace("{{ nav }}", nav)
    )


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
    nav = render_nav(request)
    habitat_options = "".join(
        f"<option value='{h}'{' selected' if h == creature['habitat'] else ''}>{h}</option>" for h in HABITATS
    )
    skill_options = "".join(
        f"<option value='{s}'{' selected' if s == creature['main_skill'] else ''}>{s}</option>" for s in SKILLS
    )
    html = (
        ENEMY_EDIT_FILE.read_text()
        .replace("{{ id }}", str(id))
        .replace("{{ habitat_options }}", habitat_options)
        .replace("{{ skill_options }}", skill_options)
        .replace("{{ nav }}", nav)
    )
    for f in CREATURE_FIELDS:
        html = html.replace(f"{{{{ {f} }}}}", esc(creature[f]))
    return html


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
    stat_rows = "".join(f"<tr><td>{skill}</td><td>{value}</td></tr>" for skill, value in stats.items())
    nav = render_nav(request)
    return (
        ENEMY_GENERATED_FILE.read_text()
        .replace("{{ name }}", esc(creature["name"]))
        .replace("{{ threat_level }}", str(threat_level))
        .replace("{{ stat_rows }}", stat_rows)
        .replace("{{ talent_name }}", esc(creature["talent_name"]))
        .replace("{{ talent_effect }}", esc(creature["talent_effect"]))
        .replace("{{ talent_uses }}", str(talent_uses))
        .replace("{{ talent_cooldown }}", str(talent_cooldown))
        .replace("{{ drops }}", esc(creature["drops"]))
        .replace("{{ nav }}", nav)
    )


@app.get("/dice", response_class=HTMLResponse)
def dice_form(request: Request):
    rank_options = "".join(f"<option value='{r}'>{r}</option>" for r in RANK_DICE)
    nav = render_nav(request)
    return (
        DICE_FILE.read_text()
        .replace("{{ rank_options }}", rank_options)
        .replace("{{ nav }}", nav)
        .replace("{{ result }}", "")
    )


@app.post("/dice", response_class=HTMLResponse)
async def roll_dice_route(request: Request):
    form = await request.form()
    rank = form.get("rank", "")
    if rank in RANK_DICE:
        roll_count, keep_count = RANK_DICE[rank]
    else:
        try:
            roll_count = int(form.get("roll_count", 1))
            keep_count = int(form.get("keep_count", 1))
        except (TypeError, ValueError):
            roll_count, keep_count = 1, 1
    roll_count = max(1, min(roll_count, MAX_DICE))
    keep_count = max(1, min(keep_count, roll_count))
    all_rolls, kept_sum = roll_and_keep(roll_count, keep_count)
    sorted_rolls = sorted(all_rolls, reverse=True)
    kept = sorted_rolls[:keep_count]
    dropped = sorted_rolls[keep_count:]
    dice_html = (
        "".join(f"<span style='font-weight:bold'>{d}</span> " for d in kept) +
        "".join(f"<span style='color:gray;text-decoration:line-through'>{d}</span> " for d in dropped)
    )
    result = f"<p>Rolled: {dice_html}<br />Kept sum: {kept_sum}</p>"
    rank_options = "".join(f"<option value='{r}'>{r}</option>" for r in RANK_DICE)
    nav = render_nav(request)
    return (
        DICE_FILE.read_text()
        .replace("{{ rank_options }}", rank_options)
        .replace("{{ nav }}", nav)
        .replace("{{ result }}", result)
    )


# Run the app with uvicorn when this file is executed directly.
def main():
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)


if __name__ == "__main__":
    main()
