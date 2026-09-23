"""Controller regressions without granting permissions or creating windows."""
import concurrent.futures
from types import SimpleNamespace

import pytest

pytest.importorskip("AppKit")

from mactranslator.desktop.notes import NotesWindow  # noqa: E402
from mactranslator.desktop.popup import TranslationPopup  # noqa: E402


def test_superseded_stream_cannot_change_popup():
    popup = TranslationPopup.__new__(TranslationPopup)
    popup.request_id = "new-request"
    popup.results = [{"id": "stable-provider-id", "output": "new result"}]
    popup.event({"type": "delta", "request_id": "old-request", "provider_id": "stable-provider-id", "text": "old"})
    assert popup.results[0]["output"] == "new result"


def test_older_note_save_response_preserves_newer_local_edit(monkeypatch):
    monkeypatch.setattr("mactranslator.desktop.notes.AppHelper.callLater", lambda *args: None)
    completions = []
    status = []

    def submit(coroutine, **kwargs):
        coroutine.close()
        completions.append(kwargs["done"])
        return concurrent.futures.Future()

    notes = NotesWindow.__new__(NotesWindow)
    notes.app = SimpleNamespace(run=submit)
    notes.loading = False
    notes.current = "note-id"
    notes.notes = [{"id": "note-id", "user_note": "original"}]
    notes.pending, notes.writes, notes.generations = {}, {}, {}
    text = ["first edit"]
    notes.editor = SimpleNamespace(string=lambda: text[0])
    notes.status = SimpleNamespace(setStringValue_=status.append)
    notes.changed()
    notes.flush()
    text[0] = "second edit while save is pending"
    notes.changed()
    completions[0]({"id": "note-id", "user_note": "first edit"})
    assert notes.notes[0]["user_note"] == text[0]
    assert notes.pending["note-id"] == text[0]
    assert status[-1] != "已保存"
