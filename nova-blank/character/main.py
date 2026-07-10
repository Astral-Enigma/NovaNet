# Character creator FastAPI app.
# Allows creating characters with any fields defined in FIELDS, saved to a CSV file.
# Install dependencies on Ubuntu:
#   sudo apt update && sudo apt install -y python3-pip
#   pip3 install fastapi uvicorn python-multipart
# Run:
#   uv run --with fastapi --with uvicorn --with python-multipart python3 main.py

import csv
import math
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI()

CSV_FILE = Path(__file__).parent / "characters.csv"
HTML_FILE = Path(__file__).parent / "index.html"
EDIT_FILE = Path(__file__).parent / "edit.html"
FIELDS = ["name", "age", "rank", "clan", "house", "trait", "trauma", "pneuma", "deftness", "handling", "tenacity", "wit", "perception", "composure", "pluck", "potential",]

if not CSV_FILE.exists():
    with open(CSV_FILE, "w", newline="") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def read_characters():
    with open(CSV_FILE, newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for f in FIELDS:
            if f not in row:
                row[f] = "0"
    return rows


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
        f"<td><a href='/character/{i}/edit'>Edit</a></td>"
        f"<td><form method='post' action='/character/{i}/delete' style='display:inline' "
        f"onsubmit=\"return confirm('Delete {c['name']}?')\">"
        f"<button type='submit'>Delete</button></form></td></tr>"
        for i, c in enumerate(characters)
    )
    return HTML_FILE.read_text().replace("{{ rows }}", rows)


@app.get("/character/{index}/edit", response_class=HTMLResponse)
def edit_character_form(index: int):
    character = read_characters()[index]
    html = EDIT_FILE.read_text().replace("{{ index }}", str(index))
    for f in FIELDS:
        html = html.replace(f"{{{{ {f} }}}}", character[f])
    return html


@app.post("/character/{index}/edit")
async def edit_character(index: int, request: Request):
    form = await request.form()
    characters = read_characters()
    characters[index] = compute_derived_fields({f: form[f] for f in FIELDS})
    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(characters)
    return RedirectResponse(url="/", status_code=303)


@app.post("/character/{index}/delete")
async def delete_character(index: int):
    characters = read_characters()
    del characters[index]
    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(characters)
    return RedirectResponse(url="/", status_code=303)


@app.post("/character")
async def create_character(request: Request):
    form = await request.form()
    characters = read_characters()
    characters.append(compute_derived_fields({f: form[f] for f in FIELDS}))
    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(characters)
    return RedirectResponse(url="/", status_code=303)


# Run the app with uvicorn when this file is executed directly.
def main():
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)


if __name__ == "__main__":
    main()
