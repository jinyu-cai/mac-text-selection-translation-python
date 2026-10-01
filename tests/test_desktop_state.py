"""Controller regressions without granting permissions or creating windows."""
import concurrent.futures
from types import SimpleNamespace

import pytest

pytest.importorskip("AppKit")

from mactranslator.desktop.notes import NotesWindow  # noqa: E402
from mactranslator.desktop.popup import TranslationPopup, VerticalClipView  # noqa: E402


@pytest.mark.parametrize("width", [272, 572, 872])
@pytest.mark.parametrize("horizontal_offset", [-80, 0, 80])
def test_popup_blocks_horizontal_scrolling_but_preserves_vertical(width, horizontal_offset):
    import AppKit as A

    clip = VerticalClipView.alloc().initWithFrame_(A.NSMakeRect(0, 0, width, 100))
    # An oversized document must not allow gestures or selection to shift the cards.
    document = A.NSView.alloc().initWithFrame_(A.NSMakeRect(0, 0, width + 200, 1000))
    clip.setDocumentView_(document)
    bounds = clip.constrainBoundsRect_(A.NSMakeRect(horizontal_offset, 120, width, 100))
    assert bounds.origin.x == 0
    assert bounds.origin.y == 120
    clip.scrollToPoint_(A.NSMakePoint(horizontal_offset, 120))
    assert clip.bounds().origin.x == 0
    assert clip.bounds().origin.y == 120


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
    assert status[-1] != "Saved"
