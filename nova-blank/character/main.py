# Character creator FastAPI app.
# Allows creating characters with any fields defined in FIELDS, saved to a SQLite database.
# Install dependencies on Ubuntu:
#   sudo apt update && sudo apt install -y python3-pip
#   pip3 install fastapi uvicorn python-multipart
# Run:
#   uv run --with fastapi --with uvicorn --with python-multipart python3 main.py

import csv
import math
import sqlite3
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI()

CSV_FILE = Path(__file__).parent / "characters.csv"
DB_FILE = Path(__file__).parent / "characters.db"
HTML_FILE = Path(__file__).parent / "index.html"
EDIT_FILE = Path(__file__).parent / "edit.html"
FIELDS = ["name", "age", "rank", "clan", "house", "trait", "trauma", "pneuma", "deftness", "handling", "tenacity", "wit", "perception", "composure", "pluck", "potential",]
NUMERIC_FIELDS = ["age", "trauma", "pneuma", "deftness", "handling", "tenacity", "wit", "perception", "composure", "pluck", "potential"]


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        conn.commit()
    finally:
        conn.close()


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
        for row in rows:
            values = to_typed_values(row)
            conn.execute(
                f"INSERT INTO characters ({', '.join(FIELDS)}) VALUES ({', '.join('?' for _ in FIELDS)})",
                values,
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
        return [dict(row) for row in conn.execute("SELECT * FROM characters ORDER BY id")]
    finally:
        conn.close()


def read_character(id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM characters WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


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


@app.get("/", response_class=HTMLResponse)
def index():
    characters = read_characters()
    rows = "".join(
        "<tr>" + "".join(f"<td>{c[f]}</td>" for f in FIELDS) +
        f"<td><a href='/character/{c['id']}/edit'>Edit</a></td>"
        f"<td><form method='post' action='/character/{c['id']}/delete' style='display:inline' "
        f"onsubmit=\"return confirm('Delete {c['name']}?')\">"
        f"<button type='submit'>Delete</button></form></td></tr>"
        for c in characters
    )
    return HTML_FILE.read_text().replace("{{ rows }}", rows)


@app.get("/character/{id}/edit", response_class=HTMLResponse)
def edit_character_form(id: int):
    character = read_character(id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    html = EDIT_FILE.read_text().replace("{{ id }}", str(id))
    for f in FIELDS:
        html = html.replace(f"{{{{ {f} }}}}", str(character[f]))
    return html


@app.post("/character/{id}/edit")
async def edit_character(id: int, request: Request):
    form = await request.form()
    character = compute_derived_fields({f: form[f] for f in FIELDS})
    values = to_typed_values(character)
    conn = get_connection()
    try:
        cursor = conn.execute(
            f"UPDATE characters SET {', '.join(f'{f} = ?' for f in FIELDS)} WHERE id = ?",
            values + [id],
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Character not found")
    finally:
        conn.close()
    return RedirectResponse(url="/", status_code=303)


@app.post("/character/{id}/delete")
async def delete_character(id: int):
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM characters WHERE id = ?", (id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Character not found")
    finally:
        conn.close()
    return RedirectResponse(url="/", status_code=303)


@app.post("/character")
async def create_character(request: Request):
    form = await request.form()
    character = compute_derived_fields({f: form[f] for f in FIELDS})
    values = to_typed_values(character)
    conn = get_connection()
    try:
        conn.execute(
            f"INSERT INTO characters ({', '.join(FIELDS)}) VALUES ({', '.join('?' for _ in FIELDS)})",
            values,
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/", status_code=303)


# Run the app with uvicorn when this file is executed directly.
def main():
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)


if __name__ == "__main__":
    main()
