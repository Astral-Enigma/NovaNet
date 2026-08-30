#!/usr/bin/env python3
"""Pull live character data out of NovaNet and back into the seed CSV.

The deployed app runs on a filesystem that is wiped on every deploy, so the database and
the characters.csv it writes are both lost each time the site ships. The only copy that
survives is the one committed to this repository, because that file is what the app seeds
from when it starts with an empty database.

This script closes that loop: fetch the live CSV, sanity-check it, write it over the
committed seed file, and optionally commit and push.

    python3 scripts/backup_characters.py                  # fetch and show what changed
    python3 scripts/backup_characters.py --commit         # ... and commit
    python3 scripts/backup_characters.py --commit --push  # ... and push, triggering a deploy

Authentication uses NOVANET_EXPORT_TOKEN, which must match the value set on the server.
Only stdlib is used so this runs anywhere Python does.
"""

import argparse
import csv
import io
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_CSV = REPO_ROOT / "nova-blank" / "character" / "characters.csv"
SEED_JSON = REPO_ROOT / "nova-blank" / "character" / "seed.json"
DEFAULT_URL = "https://novanet-yvj8.onrender.com"
REQUIRED_COLUMNS = {"name", "rank"}
# Render's free tier sleeps after inactivity and can take a minute to wake up.
TIMEOUT_SECONDS = 120


class BackupError(Exception):
    """A problem serious enough that the seed file must not be overwritten."""


def fetch(base_url, token, path):
    url = base_url.rstrip("/") + path
    if token:
        url += "?" + urllib.parse.urlencode({"token": token})
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise BackupError(f"server returned HTTP {response.status}")
            final = response.geturl()
            if "/login" in final:
                raise BackupError(
                    "the export redirected to the login page, so the token was rejected.\n"
                    "Set NOVANET_EXPORT_TOKEN to the value configured on the server."
                )
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise BackupError(f"server returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise BackupError(f"could not reach {base_url}: {exc.reason}") from exc


def fetch_csv(base_url, token):
    return fetch(base_url, token, "/export/characters.csv")


def fetch_snapshot(base_url, token):
    """The complete backup: every table, not just players and characters."""
    text = fetch(base_url, token, "/export/snapshot.json")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise BackupError(f"the snapshot was not valid JSON: {exc}") from exc
    tables = data.get("tables")
    if not isinstance(tables, dict) or "characters" not in tables:
        raise BackupError("the snapshot has no tables section; the server may be an old build")
    return text, tables


def parse_rows(text, label):
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise BackupError(f"{label} has no header row")
    missing = REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing:
        raise BackupError(f"{label} is missing expected column(s): {', '.join(sorted(missing))}")
    return list(reader), reader.fieldnames


def read_local_rows():
    if not SEED_CSV.exists():
        return [], []
    return parse_rows(SEED_CSV.read_text(), "the committed seed file")


def describe(rows):
    owners = {}
    for row in rows:
        owners.setdefault((row.get("player") or "Unassigned").strip() or "Unassigned", 0)
        owners[(row.get("player") or "Unassigned").strip() or "Unassigned"] += 1
    return owners


def run_git(args, dry_run=False):
    printable = "git " + " ".join(args)
    if dry_run:
        print(f"  would run: {printable}")
        return 0
    print(f"  {printable}")
    return subprocess.call(["git", "-C", str(REPO_ROOT)] + args)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=os.environ.get("NOVANET_URL", DEFAULT_URL),
                        help="base URL of the deployment (env: NOVANET_URL)")
    parser.add_argument("--token", default=os.environ.get("NOVANET_EXPORT_TOKEN", ""),
                        help="export token (env: NOVANET_EXPORT_TOKEN)")
    parser.add_argument("--commit", action="store_true", help="commit the refreshed seed file")
    parser.add_argument("--push", action="store_true", help="push after committing (triggers a deploy)")
    parser.add_argument("--force", action="store_true",
                        help="write even when the live data has fewer characters than the seed file")
    parser.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    args = parser.parse_args()

    try:
        # Read the committed baseline first. Requesting the export makes the server rewrite
        # its own characters.csv, which is the very file being compared against whenever the
        # app runs with its data directory inside a checkout.
        local_rows, _ = read_local_rows()

        base = args.url.rstrip("/")
        print(f"Fetching {base}/export/snapshot.json ...")
        snapshot_text, tables = fetch_snapshot(args.url, args.token)
        print(f"Fetching {base}/export/characters.csv ...")
        text = fetch_csv(args.url, args.token)
        live_rows, live_fields = parse_rows(text, "the live export")

        print(f"\n  live:      {len(live_rows)} character(s)")
        print(f"  committed: {len(local_rows)} character(s)")
        for owner, count in sorted(describe(live_rows).items()):
            print(f"    {owner}: {count}")
        print("  snapshot covers:")
        for table, rows in sorted(tables.items()):
            if rows:
                print(f"    {table}: {len(rows)}")

        if not live_rows and not args.force:
            raise BackupError(
                "the live export contains no characters. Refusing to overwrite the seed file,\n"
                "which would throw away the only surviving copy. Use --force if this is intended."
            )
        # Losing rows is the signature of a wipe that has already happened, or of catching
        # the site mid-deploy before it reseeded. Either way, do not overwrite on autopilot.
        if len(live_rows) < len(local_rows) and not args.force:
            raise BackupError(
                f"the live site has fewer characters ({len(live_rows)}) than the committed seed "
                f"file ({len(local_rows)}).\nThis usually means the live database was reset and has "
                "not been repopulated yet.\nRe-run with --force only if you are sure the live data "
                "is the copy you want to keep."
            )

        if args.dry_run:
            print("\n--dry-run: not writing anything.")
            return 0

        written = []
        if not (SEED_JSON.exists() and SEED_JSON.read_text() == snapshot_text):
            SEED_JSON.write_text(snapshot_text)
            written.append(SEED_JSON)
        if not (SEED_CSV.exists() and SEED_CSV.read_text() == text):
            SEED_CSV.write_text(text)
            written.append(SEED_CSV)
        if not written:
            print("\nSeed files already match the live data; nothing to do.")
            return 0
        print()
        for path in written:
            print(f"Wrote {path.relative_to(REPO_ROOT)}.")

        if args.commit:
            for path in written:
                if run_git(["add", str(path.relative_to(REPO_ROOT))]) != 0:
                    raise BackupError("git add failed")
            message = f"Back up live data ({len(live_rows)} characters)"
            if run_git(["commit", "-m", message]) != 0:
                raise BackupError("git commit failed")
            if args.push and run_git(["push"]) != 0:
                raise BackupError("git push failed")
        else:
            print("\nReview the change, then commit it so the next deploy seeds from it:")
            paths = " ".join(str(p.relative_to(REPO_ROOT)) for p in written)
            print(f"  git add {paths} && git commit -m 'Back up live data'")
        return 0
    except BackupError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
