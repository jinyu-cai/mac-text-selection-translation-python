import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from mactranslator import APP_NAME
from mactranslator.contracts import Note, NoteCreate, Settings


def data_directory() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_NAME


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, check_same_thread=False)
        os.chmod(path, 0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, data TEXT NOT NULL);
            PRAGMA user_version=1;
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def settings(self) -> Settings:
        row = self.db.execute("SELECT data FROM settings WHERE id=1").fetchone()
        return Settings.model_validate_json(row[0]) if row else Settings()

    def save_settings(self, settings: Settings):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES(1, ?)", (settings.model_dump_json(),))

    def notes(self) -> list[Note]:
        return [Note.model_validate_json(r[0]) for r in self.db.execute(
            "SELECT data FROM notes ORDER BY created_at DESC, id DESC")]

    def note(self, note_id: UUID) -> Note | None:
        row = self.db.execute("SELECT data FROM notes WHERE id=?", (str(note_id),)).fetchone()
        return Note.model_validate_json(row[0]) if row else None

    def add_note(self, body: NoteCreate) -> Note:
        note = Note(**body.model_dump())
        with self.db:
            self.db.execute("INSERT INTO notes VALUES(?,?,?)", (
                str(note.id), note.created_at.isoformat(), note.model_dump_json()))
        return note

    def update_note(self, note_id: UUID, text: str) -> Note | None:
        note = self.note(note_id)
        if note:
            note.user_note = text
            note.updated_at = datetime.now(timezone.utc)
            with self.db:
                self.db.execute("UPDATE notes SET data=? WHERE id=?", (note.model_dump_json(), str(note_id)))
        return note

    def delete_note(self, note_id: UUID) -> bool:
        with self.db:
            return bool(self.db.execute("DELETE FROM notes WHERE id=?", (str(note_id),)).rowcount)

    def save_with_credentials(self, settings, credentials):
        old = self.settings()
        old_flags = {p.id: p.has_api_key for p in old.providers}
        # Do not read every old key: inaccessible entries must not block changing unrelated settings.
        for p in settings.providers:
            if p.api_key is not None:
                value = p.api_key.get_secret_value().strip()
                credentials.set(str(p.id), value)
                p.has_api_key = bool(value)
            else:
                p.has_api_key = old_flags.get(p.id, False)
        self.save_settings(settings)
        # Retired credentials are best-effort cleanup; saved configuration is the source of truth.
        from .credentials import CredentialError
        for removed in {p.id for p in old.providers} - {p.id for p in settings.providers}:
            try:
                credentials.set(str(removed), "")
            except CredentialError:
                pass
        return Settings.model_validate(json.loads(settings.model_dump_json()))
