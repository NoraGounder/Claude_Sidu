"""Backups (D23): encrypted round trip, the off-site vault as a local bare git repo, the launch guard."""

import sqlite3
import subprocess

import pytest

from gtm import backup


@pytest.fixture
def env(tmp_path, monkeypatch):
    data, clients = tmp_path / "data", tmp_path / "clients"
    (clients / "acme" / "private").mkdir(parents=True)
    (clients / "acme" / "private" / "exclusions.csv").write_text("domain\nexample.org\n", encoding="utf-8")
    data.mkdir()
    monkeypatch.setenv("GTM_DATA_DIR", str(data))
    monkeypatch.setenv("GTM_CLIENTS_DIR", str(clients))
    monkeypatch.delenv(backup.KEY_ENV, raising=False)
    monkeypatch.delenv(backup.REMOTE_ENV, raising=False)
    conn = sqlite3.connect(data / "engine.db")
    conn.execute("CREATE TABLE t (x TEXT)")
    conn.execute("INSERT INTO t VALUES ('synthetic')")
    conn.commit()
    conn.close()
    return tmp_path


def bare_remote(tmp_path):
    remote = tmp_path / "vault.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    return str(remote)


def test_encrypt_round_trip_and_wrong_key():
    blob = backup.encrypt(b"secret data", "correct horse")
    assert blob.startswith(backup.MAGIC) and b"secret data" not in blob
    assert backup.decrypt(blob, "correct horse") == b"secret data"
    with pytest.raises(backup.BackupError):
        backup.decrypt(blob, "wrong")


def test_local_backup_without_key_is_not_fresh(env):
    r = backup.backup("acme")
    assert not r["offsite"] and not r["encrypted"]
    fresh, why = backup.is_fresh("acme")
    assert not fresh and "local only" in why


def test_vault_backup_restore_and_guard(env, monkeypatch):
    monkeypatch.setenv(backup.KEY_ENV, "test-passphrase")
    monkeypatch.setenv(backup.REMOTE_ENV, bare_remote(env))
    r = backup.backup("acme")
    assert r["offsite"] and r["encrypted"]
    assert backup.is_fresh("acme")[0]

    # A change to the database makes the backup stale.
    conn = sqlite3.connect(env / "data" / "engine.db")
    conn.execute("INSERT INTO t VALUES ('changed')")
    conn.commit()
    conn.close()
    assert not backup.is_fresh("acme")[0]

    # A fresh machine: no database, no private files, no local vault clone.
    (env / "data" / "engine.db").unlink()
    (env / "clients" / "acme" / "private" / "exclusions.csv").unlink()
    import shutil
    shutil.rmtree(env / "data" / "vault")
    out = backup.restore("acme")
    assert "engine.db" in out["written"]
    rows = sqlite3.connect(env / "data" / "engine.db").execute("SELECT x FROM t").fetchall()
    assert rows == [("synthetic",)]
    assert (env / "clients" / "acme" / "private" / "exclusions.csv").exists()
    with pytest.raises(backup.BackupError):
        backup.restore("acme")          # refuses to overwrite without force


def test_vault_keeps_latest_and_one_commit(env, monkeypatch):
    remote = bare_remote(env)
    monkeypatch.setenv(backup.KEY_ENV, "k")
    monkeypatch.setenv(backup.REMOTE_ENV, remote)
    names = set()
    for i in range(4):
        names.add(backup.backup("acme", keep=2)["file"])
        conn = sqlite3.connect(env / "data" / "engine.db")
        conn.execute("INSERT INTO t VALUES (?)", (str(i),))
        conn.commit()
        conn.close()
        import time
        time.sleep(1.1)                 # file names are per second
    listing = subprocess.run(["git", "--git-dir", remote, "ls-tree", "-r", "--name-only", "main"],
                             capture_output=True, text=True, check=True).stdout.split()
    assert len(listing) == 2 and all(n.startswith("acme/") for n in listing)
    commits = subprocess.run(["git", "--git-dir", remote, "rev-list", "--count", "main"],
                             capture_output=True, text=True, check=True).stdout.strip()
    assert commits == "1"


def test_cli_guard_refuses_start_without_backup_only_when_required(env, monkeypatch, capsys):
    from gtm.cli import _backup_guard
    monkeypatch.delenv("GTM_BACKUP_GUARD", raising=False)
    monkeypatch.setattr("gtm.cli.load_client", lambda c: object())
    monkeypatch.setattr("gtm.layers.l6_send.load_sending", lambda cfg: {"require_backup": True})
    assert _backup_guard("acme") is False
    assert "Refused" in capsys.readouterr().out
    monkeypatch.setattr("gtm.layers.l6_send.load_sending", lambda cfg: {})
    assert _backup_guard("acme") is True          # opt-in: clients without the key are unchanged
