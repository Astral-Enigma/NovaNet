"""Safety rails on the backup script.

The script overwrites the only surviving copy of the character data, so the cases that
matter most are the ones where it must refuse to write.
"""

import csv
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("backup_characters", REPO_ROOT / "scripts" / "backup_characters.py")
backup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backup
spec.loader.exec_module(backup)

HEADER = ("player,player_is_hm,name,age,rank,clan,house,trait,trauma,pneuma,"
          "deftness,handling,tenacity,wit,perception,composure,pluck,potential")


def row(name, player="Kira"):
    return f"{player},0,{name},17,Novice,Varna,Zealot,Pyre,0,10,3,2,4,2,2,3,8,4"


def csv_text(names):
    return "\n".join([HEADER] + [row(n) for n in names]) + "\n"


@pytest.fixture
def seed(tmp_path, monkeypatch):
    path = tmp_path / "characters.csv"
    monkeypatch.setattr(backup, "SEED_CSV", path)
    monkeypatch.setattr(backup, "SEED_JSON", tmp_path / "seed.json")
    monkeypatch.setattr(backup, "REPO_ROOT", tmp_path)
    return path


def snapshot_for(names):
    return {"players": [{"id": 1, "name": "Kira"}],
            "characters": [{"id": i + 1, "name": n} for i, n in enumerate(names)],
            "techniques": [{"id": 1, "character_id": 1, "name": "Empowered Strike"}]}


def run(monkeypatch, seed, live_text, argv=(), snapshot=None):
    rows = list(csv.DictReader(io.StringIO(live_text))) if live_text.strip() else []
    names = [r["name"] for r in rows if r.get("name")]
    tables = snapshot if snapshot is not None else snapshot_for(names)
    monkeypatch.setattr(backup, "fetch_csv", lambda url, token: live_text)
    monkeypatch.setattr(backup, "fetch_snapshot",
                        lambda url, token: (json.dumps({"tables": tables}), tables))
    monkeypatch.setattr(sys, "argv", ["backup_characters.py", *argv])
    return backup.main()


class TestValidation:
    def test_rejects_a_response_with_no_header(self, monkeypatch, seed):
        seed.write_text(csv_text(["Ryn"]))
        assert run(monkeypatch, seed, "") == 1
        assert seed.read_text() == csv_text(["Ryn"]), "seed file must be untouched"

    def test_rejects_a_response_missing_expected_columns(self, monkeypatch, seed):
        seed.write_text(csv_text(["Ryn"]))
        assert run(monkeypatch, seed, "colour,size\nred,large\n") == 1
        assert seed.read_text() == csv_text(["Ryn"])

    def test_rejects_html_served_instead_of_csv(self, monkeypatch, seed):
        """A login redirect or an error page must never be written over the seed."""
        seed.write_text(csv_text(["Ryn"]))
        assert run(monkeypatch, seed, "<!DOCTYPE html><html><body>Not Found</body></html>") == 1
        assert seed.read_text() == csv_text(["Ryn"])


class TestDataLossGuards:
    def test_refuses_an_empty_live_export(self, monkeypatch, seed):
        seed.write_text(csv_text(["Ryn", "Odo"]))
        assert run(monkeypatch, seed, HEADER + "\n") == 1
        assert seed.read_text() == csv_text(["Ryn", "Odo"])

    def test_refuses_when_live_has_fewer_characters(self, monkeypatch, seed):
        """The signature of a database that was wiped and has not been repopulated."""
        seed.write_text(csv_text(["Ryn", "Odo", "Cymon"]))
        assert run(monkeypatch, seed, csv_text(["Ryn"])) == 1
        assert seed.read_text() == csv_text(["Ryn", "Odo", "Cymon"])

    def test_force_overrides_the_shrink_guard(self, monkeypatch, seed):
        seed.write_text(csv_text(["Ryn", "Odo", "Cymon"]))
        assert run(monkeypatch, seed, csv_text(["Ryn"]), ["--force"]) == 0
        assert seed.read_text() == csv_text(["Ryn"])

    def test_dry_run_never_writes(self, monkeypatch, seed):
        seed.write_text(csv_text(["Ryn"]))
        assert run(monkeypatch, seed, csv_text(["Ryn", "Odo"]), ["--dry-run"]) == 0
        assert seed.read_text() == csv_text(["Ryn"])


class TestHappyPath:
    def test_writes_when_live_has_more_characters(self, monkeypatch, seed):
        seed.write_text(csv_text(["Ryn"]))
        assert run(monkeypatch, seed, csv_text(["Ryn", "Odo"])) == 0
        assert seed.read_text() == csv_text(["Ryn", "Odo"])

    def test_writes_when_the_seed_file_does_not_exist_yet(self, monkeypatch, seed):
        assert run(monkeypatch, seed, csv_text(["Ryn"])) == 0
        assert seed.read_text() == csv_text(["Ryn"])

    def test_identical_data_is_a_no_op(self, monkeypatch, seed):
        seed.write_text(csv_text(["Ryn"]))
        assert run(monkeypatch, seed, csv_text(["Ryn"])) == 0  # first run writes seed.json
        before = seed.stat().st_mtime_ns
        assert run(monkeypatch, seed, csv_text(["Ryn"])) == 0
        assert seed.stat().st_mtime_ns == before, "unchanged data should not rewrite the file"

    def test_the_snapshot_is_written_too(self, monkeypatch, seed):
        assert run(monkeypatch, seed, csv_text(["Ryn"])) == 0
        data = json.loads(backup.SEED_JSON.read_text())
        assert [c["name"] for c in data["tables"]["characters"]] == ["Ryn"]
        assert data["tables"]["techniques"], "techniques must be captured, not just characters"

    def test_a_snapshot_without_tables_is_rejected(self, monkeypatch, seed):
        seed.write_text(csv_text(["Ryn"]))
        monkeypatch.setattr(backup, "fetch_snapshot", backup.fetch_snapshot)
        monkeypatch.setattr(backup, "fetch", lambda url, token, path: "{}")
        monkeypatch.setattr(sys, "argv", ["backup_characters.py"])
        assert backup.main() == 1
        assert seed.read_text() == csv_text(["Ryn"])

    def test_does_not_commit_unless_asked(self, monkeypatch, seed):
        calls = []
        monkeypatch.setattr(backup, "run_git", lambda *a, **k: calls.append(a) or 0)
        run(monkeypatch, seed, csv_text(["Ryn"]))
        assert calls == []

    def test_commit_flag_stages_and_commits(self, monkeypatch, seed):
        calls = []
        monkeypatch.setattr(backup, "run_git", lambda args, **k: calls.append(args) or 0)
        assert run(monkeypatch, seed, csv_text(["Ryn"]), ["--commit"]) == 0
        staged = [a[1] for a in calls if a[0] == "add"]
        assert any("seed.json" in f for f in staged), "the snapshot must be staged"
        assert any("characters.csv" in f for f in staged), "the csv must be staged"
        assert calls[-1][0] == "commit"
        assert not any(a[0] == "push" for a in calls), "must not push without --push"

    def test_push_flag_pushes(self, monkeypatch, seed):
        calls = []
        monkeypatch.setattr(backup, "run_git", lambda args, **k: calls.append(args) or 0)
        assert run(monkeypatch, seed, csv_text(["Ryn"]), ["--commit", "--push"]) == 0
        assert any(a[0] == "push" for a in calls)


class TestFetch:
    def test_login_redirect_is_reported_clearly(self, monkeypatch):
        class FakeResponse:
            status = 200
            def read(self): return b"<html>login</html>"
            def geturl(self): return "https://example.com/login"
            def __enter__(self): return self
            def __exit__(self, *a): return False

        monkeypatch.setattr(backup.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
        with pytest.raises(backup.BackupError, match="token was rejected"):
            backup.fetch_csv("https://example.com", "bad-token")

    def test_token_is_sent_as_a_query_parameter(self, monkeypatch):
        seen = {}

        class FakeResponse:
            status = 200
            def read(self): return (HEADER + "\n").encode()
            def geturl(self): return seen["url"]
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(url, **kwargs):
            seen["url"] = url
            return FakeResponse()

        monkeypatch.setattr(backup.urllib.request, "urlopen", fake_urlopen)
        backup.fetch_csv("https://example.com", "s3cret")
        assert "token=s3cret" in seen["url"]
