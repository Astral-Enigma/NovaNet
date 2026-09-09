"""Test fixtures for NovaNet.

Each test gets its own temporary data directory, so the app never touches the real
database or the committed seed CSV.
"""

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "nova-blank" / "character"


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    """Load main.py against a throwaway data directory and an empty seed CSV."""
    monkeypatch.setenv("NOVANET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NOVANET_SECRET_KEY", "test-secret-not-used-anywhere-real")

    # main.py imports its sibling modules by name, so the app directory has to be on the
    # path when it is loaded from a file location rather than as a package.
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))

    spec = importlib.util.spec_from_file_location(f"novanet_{tmp_path.name}", APP_DIR / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    # main.py seeds from the committed characters.csv at import time, before this fixture can
    # intervene. Repoint the CSV at a throwaway copy so exports never rewrite the real file,
    # then clear the seeded rows so each test starts from an genuinely empty database.
    seed_copy = tmp_path / "characters.csv"
    seed_copy.write_text("")
    module.CSV_FILE = seed_copy
    module.SNAPSHOT_FILE = tmp_path / "seed.json"

    # Clear every table the snapshot restores, derived from the app rather than hardcoded:
    # a list written by hand goes stale the moment a table is added, and a stale one let
    # real session data out of the committed seed.json leak into these tests.
    conn = module.get_connection()
    for table in reversed(module.SNAPSHOT_TABLES):
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM sqlite_sequence")
    conn.commit()
    conn.close()
    # The catalog is reference data the app ships, so put it back after the wipe.
    module.seed_creature_catalog()

    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture
def client(app_module):
    from fastapi.testclient import TestClient
    with TestClient(app_module.app) as c:
        yield c


@pytest.fixture
def player(client):
    """An enrolled, logged-in player. Returns the session-bearing client."""
    client.post("/enroll", data={"name": "Kira"}, follow_redirects=False)
    return client


def make_character(client, name, rank="Novice", **overrides):
    """Create a character through the real form and return its id."""
    payload = {
        "name": name, "age": "17", "rank": rank, "clan": "Varna", "house": "Zealot",
        "trait": "Pyre", "trauma": "0", "pneuma": "10", "deftness": "3", "handling": "2",
        "tenacity": "4", "wit": "2", "perception": "2", "composure": "3",
        "pluck": "0", "potential": "0",
    }
    payload.update(overrides)
    client.post("/character", data=payload, follow_redirects=False)
    listing = client.get("/characters").text
    marker = f"/character/"
    # The edit link for the newest row carries the id we just created.
    ids = [int(s.split("/")[2]) for s in listing.split("'") if s.startswith("/character/") and s.endswith("/edit")]
    return ids[-1] if ids else None
