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


def suggestion_popup():
    popup = TranslationPopup.__new__(TranslationPopup)
    calls = []
    popup.app = SimpleNamespace(settings=SimpleNamespace(enable_notes=True),
                                request=lambda *args, **kwargs: calls.append((args, kwargs)))
    popup.request_id = "current"
    popup.render = lambda: None
    popup.suggestions = []
    popup.suggestions_loading = True
    popup.suggestions_error = None
    popup.suggestions_done({"request_id": "current", "backend_name": "Guesser", "suggestions": [
        {"term": "take off", "meaning": "起飞", "context": "Planes take off here."}]})
    return popup, calls


def test_suggestion_save_retry_and_independent_states():
    popup, calls = suggestion_popup()
    popup.saved = True  # Saving the whole translation must not block word saves.
    popup.save_suggestion(0)
    popup.save_suggestion(0)
    assert len(calls) == 1
    assert calls[0][1]["json"]["context"] == "Planes take off here."
    assert calls[0][1]["json"]["backend_name"] == "Guesser"
    calls[0][1]["error"](RuntimeError("Try again"))
    assert popup.suggestions[0]["save_state"] == "idle"
    popup.save_suggestion(0)
    calls[1][1]["done"]({})
    popup.save_suggestion(0)
    assert len(calls) == 2 and popup.suggestions[0]["save_state"] == "saved"


def test_stale_suggestions_errors_and_saves_do_not_affect_new_request():
    popup, calls = suggestion_popup()
    popup.save_suggestion(0)
    popup.request_id = "new"
    popup.suggestions = []
    popup.suggestions_loading = True
    popup.suggestions_done({"request_id": "current", "backend_name": "old", "suggestions": []})
    popup.suggestions_failed("current", RuntimeError("old failure"))
    calls[0][1]["error"](RuntimeError("old save failed"))
    calls[0][1]["done"]({})
    assert popup.suggestions == [] and popup.suggestions_loading
    assert popup.suggestions_error is None


def test_suggestion_failure_does_not_change_translation():
    popup, _ = suggestion_popup()
    popup.results = [{"output": "Translation still streaming", "loading": True}]
    popup.loading = True
    popup.suggestions_failed("current", RuntimeError("Guess failed"))
    assert popup.loading and popup.results[0]["loading"]
    assert not popup.suggestions_loading and popup.suggestions_error == "Guess failed"


def test_translation_starts_both_requests_and_cancels_both(monkeypatch):
    from mactranslator.desktop.app import TranslatorApp
    app = TranslatorApp.__new__(TranslatorApp)
    app.ready = True
    app.settings = SimpleNamespace(enable_notes=True, enable_word_suggestions=True)
    app.translation_task = app.suggestions_task = None
    app.stop_speech = lambda: None
    calls, futures = [], []
    app.popup = SimpleNamespace(show=lambda *args: calls.append("show"), event=lambda _: None,
                                failed=lambda *args: None, suggestions_done=lambda _: None,
                                suggestions_failed=lambda *args: None)

    async def stream(*args):
        pass

    app.runtime = SimpleNamespace(stream=stream)

    def run(coroutine, **kwargs):
        coroutine.close()
        calls.append("translation")
        future = concurrent.futures.Future()
        futures.append(future)
        return future

    def request(*args, **kwargs):
        calls.append("suggestions")
        future = concurrent.futures.Future()
        futures.append(future)
        return future

    app.run, app.request = run, request
    app.translate("Planes take off here.")
    assert calls == ["show", "translation", "suggestions"]
    app.cancel_translation()
    assert all(f.cancelled() for f in futures)
    assert app.popup.request_id is None


def test_note_copy_includes_context_and_legacy_still_works(monkeypatch):
    copied = []
    monkeypatch.setattr("mactranslator.desktop.notes.copy_text", copied.append)
    notes = NotesWindow.__new__(NotesWindow)
    notes.current = "word"
    notes.editor = SimpleNamespace(string=lambda: "My annotation")
    note = {"id": "word", "source_text": "take off", "translated_text": "起飞",
            "context": "Planes take off here."}
    notes.notes = [note]
    notes.copy()
    assert copied[-1] == "take off\n\n起飞\n\nPlanes take off here.\n\nMy annotation"
    del note["context"]
    notes.copy()
    assert copied[-1] == "take off\n\n起飞\n\nMy annotation"
