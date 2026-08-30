# Backing up live character data

NovaNet runs on Render's free tier, where the filesystem is wiped on every deploy. The
database does not survive one, and neither do the seed files the app writes beside it. The
only copy that lives through a deploy is the one **committed to this repository**, because
that is what the app reloads from when it starts with an empty database.

`backup_characters.py` closes that loop. It writes two files:

- **`seed.json`** — the complete backup: players, characters, techniques, creatures, rooms,
  room membership, the message log, and generated enemies. This is what the app restores
  from, and it preserves row ids so techniques stay attached to their characters and the
  log stays attached to its room.
- **`characters.csv`** — players and characters only, kept because it is readable at a
  glance and because it is the fallback for a database seeded before snapshots existed.

Only `characters.csv` used to be backed up, which meant **techniques and session logs were
lost on every deploy** with no way to get them back.

## One-time setup

The export endpoint needs a token so the script can authenticate without a browser session.
`render.yaml` declares `NOVANET_EXPORT_TOKEN` with `generateValue: true`, so Render creates
one on the next deploy. Copy it out of the Render dashboard (Environment → the service →
`NOVANET_EXPORT_TOKEN`) and put it in your shell:

```bash
export NOVANET_EXPORT_TOKEN='...the value from Render...'
```

Optionally set `NOVANET_URL` if the deployment moves; it defaults to the current one.

## Use

`scripts/...` is a **relative path, so these only work from the repository root.** Running
them from `nova-blank/character` - where you would be to start the server - fails with
`can't open file '.../nova-blank/character/scripts/backup_characters.py'`.

```bash
cd ~/workspace/NovaNet

# See what is live and what would change, without writing anything
./scripts/backup_characters.py --dry-run

# Refresh the committed seed files
./scripts/backup_characters.py

# Refresh and commit them
./scripts/backup_characters.py --commit

# Refresh, commit, and push - note this triggers a deploy, which wipes the live database.
# It comes straight back from the seed files you just committed.
./scripts/backup_characters.py --commit --push
```

The script itself does not care where you run it from: it locates the repository from its
own location, so an absolute path works from anywhere and always writes to the right files.

```bash
~/workspace/NovaNet/scripts/backup_characters.py --dry-run   # works from any directory
```

**Run this before any deploy that matters.** A deploy resets live data to whatever the
committed CSV holds, so an un-backed-up character created through the UI is lost.

## Safety rails

The script writes over the only surviving copy of the data, so it refuses when something
looks wrong:

- The snapshot is not valid JSON, or has no `tables` section (an old build, an error page,
  or a login redirect served instead of data).
- The CSV is not a CSV, or is missing expected columns.
- The live export contains no characters at all.
- The live site has **fewer** characters than the committed file. That is the signature of
  a database that was already wiped and has not been repopulated, or of catching the site
  mid-deploy. Override with `--force` only when the live copy really is the one to keep.

Nothing is committed or pushed unless you pass `--commit` / `--push`.

## What this does not solve

This is a manual loop, and it only protects data that was backed up *before* a deploy. The
permanent fixes remain a paid Render instance with a persistent disk (`render.yaml` has the
config commented out ready to go) or a managed database.
