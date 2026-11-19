"""Encrypted backups of the engine database and a client's private files (The Marble Jar D23).

A backup is one file: the SQLite database (copied with SQLite's online backup) and
`clients/<client>/private/`, packed as tar.gz and encrypted with a passphrase from GTM_BACKUP_KEY
(scrypt key derivation, then Fernet: AES-128-CBC with HMAC-SHA256). The key is never printed or stored.

Where it goes:
- GTM_BACKUP_REMOTE set (the git URL of a private repository used only for backups, never the code
  repository): the file is committed under `<client>/` there, only the newest KEEP files are kept, and
  the branch is rewritten as a single commit, so older snapshots do not pile up in history.
- otherwise: `data/backups/<client>/` in this machine only, with a warning (not off-site).

`state.json` next to the local copies records the SHA-256 of the database file at backup time.
`is_fresh` compares it with the current file, so `push --live` and `start` can refuse to run while
the last change is not backed up off-site.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from gtm.config import clients_dir, data_dir

KEY_ENV = "GTM_BACKUP_KEY"
REMOTE_ENV = "GTM_BACKUP_REMOTE"
KEEP = 14
MAGIC = b"GTMBAK1\n"
SUFFIX = ".gtmbak"


class BackupError(RuntimeError):
    pass


# ---------- helpers ----------

def db_file() -> Path:
    return data_dir() / "engine.db"


def file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def configured() -> bool:
    return bool(os.environ.get(KEY_ENV)) and bool(os.environ.get(REMOTE_ENV))


def _fernet(passphrase: str, salt: bytes):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    key = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(data: bytes, passphrase: str) -> bytes:
    if not passphrase:
        raise BackupError(f"{KEY_ENV} is empty.")
    salt = os.urandom(16)
    return MAGIC + salt + _fernet(passphrase, salt).encrypt(data)


def decrypt(blob: bytes, passphrase: str) -> bytes:
    from cryptography.fernet import InvalidToken

    if not blob.startswith(MAGIC):
        raise BackupError("Not a gtm backup file.")
    salt, token = blob[len(MAGIC):len(MAGIC) + 16], blob[len(MAGIC) + 16:]
    try:
        return _fernet(passphrase, salt).decrypt(token)
    except InvalidToken:
        raise BackupError(f"Wrong {KEY_ENV}, or the file is damaged.") from None


def pack(client: str, db_path: Path) -> bytes:
    """tar.gz with engine.db (consistent online copy) and the client's private/ folder."""
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "engine.db"
        if db_path.exists():
            src = sqlite3.connect(db_path)
            dst = sqlite3.connect(copy)
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            if copy.exists():
                tar.add(copy, arcname="engine.db")
            private = clients_dir() / client / "private"
            if private.is_dir():
                tar.add(private, arcname="private")
    return buf.getvalue()


def unpack(data: bytes, client: str, db_path: Path, force: bool = False) -> list[str]:
    """Write engine.db and private/ back. Existing files are kept unless force."""
    done: list[str] = []
    private = clients_dir() / client / "private"
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            name = member.name
            if not member.isfile() or name.startswith("/") or ".." in Path(name).parts:
                continue
            if name == "engine.db":
                target = db_path
            elif name.startswith("private/"):
                target = private / Path(name).relative_to("private")
            else:
                continue
            if target.exists() and not force:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
            done.append(name)
    return done


# ---------- state ----------

def _local_dir(client: str) -> Path:
    return data_dir() / "backups" / client


def _state_path() -> Path:
    return data_dir() / "backups" / "state.json"


def _read_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(client: str, entry: dict) -> None:
    state = _read_state()
    state[client] = entry
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps(state, indent=1), encoding="utf-8")


def last_backup(client: str) -> dict | None:
    return _read_state().get(client)


def is_fresh(client: str) -> tuple[bool, str]:
    """True when the current database is exactly the one last backed up off-site."""
    entry = last_backup(client)
    if not entry:
        return False, "no backup has been made on this machine"
    if not entry.get("offsite"):
        return False, f"the last backup ({entry.get('at')}) is local only; set {KEY_ENV} and {REMOTE_ENV}"
    if entry.get("db_sha256") != file_sha256(db_file()):
        return False, f"the database changed after the last backup ({entry.get('at')})"
    return True, f"backed up {entry.get('at')}"


# ---------- vault (git) ----------

def _git(args: list[str], cwd: Path) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        # Never echo the remote URL: it could carry a token.
        raise BackupError(f"git {args[0]} failed: {res.stderr.strip().splitlines()[-1] if res.stderr.strip() else res.returncode}")
    return res.stdout


def _vault(remote: str) -> Path:
    vault = data_dir() / "vault"
    if not (vault / ".git").exists():
        if vault.exists():
            shutil.rmtree(vault)
        vault.mkdir(parents=True)
        _git(["init", "-q", "-b", "main"], vault)
        _git(["remote", "add", "origin", remote], vault)
    else:
        _git(["remote", "set-url", "origin", remote], vault)
    has_main = subprocess.run(["git", "ls-remote", "--exit-code", "origin", "main"], cwd=vault,
                              capture_output=True, timeout=120).returncode == 0
    if has_main:
        _git(["fetch", "-q", "--depth", "1", "origin", "main"], vault)
        _git(["reset", "-q", "--hard", "FETCH_HEAD"], vault)
    return vault


def _publish(vault: Path, message: str) -> None:
    _git(["checkout", "-q", "--orphan", "snap"], vault)
    _git(["add", "-A"], vault)
    _git(["-c", "user.name=gtm-backup", "-c", "user.email=backup@localhost", "commit", "-q", "-m", message], vault)
    _git(["branch", "-q", "-M", "main"], vault)
    _git(["push", "-q", "-f", "origin", "main"], vault)


def _prune(folder: Path, keep: int) -> int:
    files = sorted(folder.glob(f"*{SUFFIX}"))
    gone = files[:-keep] if keep and len(files) > keep else []
    for f in gone:
        f.unlink()
    return len(gone)


# ---------- commands ----------

def backup(client: str, keep: int = KEEP) -> dict:
    """Make one backup. Returns {path, offsite, encrypted, bytes, at}."""
    key, remote = os.environ.get(KEY_ENV), os.environ.get(REMOTE_ENV)
    path_db = db_file()
    sha = file_sha256(path_db)
    data = pack(client, path_db)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if key:
        blob, name = encrypt(data, key), f"{stamp}{SUFFIX}"
    else:
        blob, name = data, f"{stamp}.tar.gz"
    local = _local_dir(client)
    local.mkdir(parents=True, exist_ok=True)
    (local / name).write_bytes(blob)
    _prune(local, keep)
    for old in sorted(local.glob("*.tar.gz"))[:-2]:   # plain local copies: keep two at most
        old.unlink()
    offsite = False
    if key and remote:
        vault = _vault(remote)
        folder = vault / client
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(blob)
        _prune(folder, keep)
        _publish(vault, f"{client} backup {stamp}")
        offsite = True
    entry = {"at": at, "file": name, "db_sha256": sha, "offsite": offsite, "encrypted": bool(key),
             "bytes": len(blob)}
    _write_state(client, entry)
    return {**entry, "path": str(local / name)}


def restore(client: str, file: Path | None = None, force: bool = False) -> dict:
    """Restore the newest backup (or `file`). Existing files are kept unless force."""
    key, remote = os.environ.get(KEY_ENV), os.environ.get(REMOTE_ENV)
    if file is None:
        if not remote:
            raise BackupError(f"{REMOTE_ENV} is not set; pass --file to restore a local backup.")
        vault = _vault(remote)
        files = sorted((vault / client).glob(f"*{SUFFIX}"))
        if not files:
            raise BackupError(f"No backups for {client} in the vault.")
        file = files[-1]
    blob = Path(file).read_bytes()
    if blob.startswith(MAGIC):
        if not key:
            raise BackupError(f"{KEY_ENV} is not set; the backup is encrypted.")
        blob = decrypt(blob, key)
    if db_file().exists() and not force:
        raise BackupError("data/engine.db exists; add --force to replace it.")
    written = unpack(blob, client, db_file(), force=force)
    entry = {"at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "file": Path(file).name,
             "db_sha256": file_sha256(db_file()), "offsite": bool(remote), "encrypted": True,
             "restored": True}
    _write_state(client, entry)
    return {"file": Path(file).name, "written": written}
