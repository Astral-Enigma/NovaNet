# Character creator FastAPI app.
# Allows creating characters with name, age, and health, saved to a CSV file.
# Install dependencies on Ubuntu:
#   sudo apt update && sudo apt install -y python3-pip
#   pip3 install fastapi uvicorn python-multipart
# Run:
#   uv run --with fastapi --with uvicorn --with python-multipart python3 main.py

import csv
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI()

CSV_FILE = Path(__file__).parent / "characters.csv"
HTML_FILE = Path(__file__).parent / "index.html"
EDIT_FILE = Path(__file__).parent / "edit.html"
FIELDS = ["name", "age", "health"]


# Ensure the CSV file exists with a header row.
def init_csv():
    if not CSV_FILE.exists():
        with open(CSV_FILE, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


# Read all characters from the CSV file.
def read_characters():
    init_csv()
    with open(CSV_FILE, newline="") as f:
        return list(csv.DictReader(f))


# Append a new character to the CSV file.
def write_character(name: str, age: int, health: int):
    init_csv()
    with open(CSV_FILE, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerow(
            {"name": name, "age": age, "health": health}
        )


# Serve the main HTML page, injecting the current character list.
@app.get("/", response_class=HTMLResponse)
def index():
    characters = read_characters()
    rows = "".join(
        f"<tr><td>{c['name']}</td><td>{c['age']}</td><td>{c['health']}</td>"
        f"<td><a href='/character/{i}/edit'>Edit</a></td></tr>"
        for i, c in enumerate(characters)
    )
    html = HTML_FILE.read_text().replace("{{ rows }}", rows)
    return html


# Serve the edit form pre-filled with the character's current values.
@app.get("/character/{index}/edit", response_class=HTMLResponse)
def edit_character_form(index: int):
    character = read_characters()[index]
    html = (
        EDIT_FILE.read_text()
        .replace("{{ index }}", str(index))
        .replace("{{ name }}", character["name"])
        .replace("{{ age }}", character["age"])
        .replace("{{ health }}", character["health"])
    )
    return html


# Save the updated character back to the CSV and redirect to the list.
@app.post("/character/{index}/edit")
def edit_character(
    index: int,
    name: str = Form(...),
    age: int = Form(...),
    health: int = Form(...),
):
    characters = read_characters()
    characters[index] = {"name": name, "age": age, "health": health}
    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(characters)
    return RedirectResponse(url="/", status_code=303)


# Accept a form submission, save the character, and redirect back to the list.
@app.post("/character")
def create_character(
    name: str = Form(...), age: int = Form(...), health: int = Form(...)
):
    write_character(name, age, health)
    return RedirectResponse(url="/", status_code=303)


# Run the app with uvicorn when this file is executed directly.
def main():
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)


if __name__ == "__main__":
    main()
