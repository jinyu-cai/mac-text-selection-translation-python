"""Exercise selection capture without accessing applications or the real clipboard."""
import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("AppKit")

from mactranslator.desktop import native  # noqa: E402


TEXT_TYPE = "public.utf8-plain-text"
SOURCE = (
    "The XSTest Suite\n"
    "• Safe prompts: 学习中文 and café 🧪.\n"
    "• These catch models that simply comply with every request."
)


class PasteboardItem:
    def __init__(self, data=None):
        self.data = dict(data or {})

    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return self

    def types(self):
        return list(self.data)

    def dataForType_(self, kind):
        return self.data.get(kind)

    def setData_forType_(self, data, kind):
        self.data[kind] = data


class Pasteboard:
    def __init__(self):
        self.items = [PasteboardItem({TEXT_TYPE: b"Old clipboard text"})]
        self.count = 10
        self.clears = 0
        self.after_read = lambda: None

    def put(self, items):
        self.items = [PasteboardItem(data) for data in items]
        self.count += 1

    def pasteboardItems(self):
        return self.items

    def changeCount(self):
        return self.count

    def stringForType_(self, kind):
        data = next((item.data[kind] for item in self.items if kind in item.data), None)
        self.after_read()
        return data.decode("utf-8") if data is not None else None

    def clearContents(self):
        self.clears += 1
        self.put([])

    def writeObjects_(self, items):
        self.put([item.data for item in items])

    def contents(self):
        return [item.data for item in self.items]


@pytest.fixture
def capture(monkeypatch):
    pb = Pasteboard()
    state = SimpleNamespace(pb=pb, ax_text=None, copy_text=SOURCE, copies=0, polls=0,
                            on_copy=None, on_poll=None)

    async def on_main(function):
        return function()

    async def sleep(delay):
        if delay == 0.015:
            state.polls += 1
            if state.on_poll:
                state.on_poll()

    def simulate_copy():
        state.copies += 1
        if state.on_copy:
            state.on_copy()
        elif state.copy_text is not None:
            pb.put([{TEXT_TYPE: state.copy_text.encode("utf-8")}])

    monkeypatch.setattr(native, "A", SimpleNamespace(
        NSEvent=SimpleNamespace(pressedMouseButtons=lambda: 0),
        NSPasteboard=SimpleNamespace(generalPasteboard=lambda: pb),
        NSPasteboardItem=PasteboardItem, NSPasteboardTypeString=TEXT_TYPE))
    monkeypatch.setattr(native, "asyncio", SimpleNamespace(sleep=sleep))
    monkeypatch.setattr(native, "on_main", on_main)
    monkeypatch.setattr(native, "selected_text", lambda: state.ax_text)
    monkeypatch.setattr(native, "simulate_copy", simulate_copy)
    return state


@pytest.mark.parametrize("ax_text", [SOURCE[:25], SOURCE[12:], SOURCE[:-18]])
async def test_fresh_copy_replaces_partial_or_shifted_accessibility_text(capture, ax_text):
    capture.ax_text = ax_text
    assert await native.capture_selection() == SOURCE
    assert capture.copies == 1


async def test_fresh_copy_wins_even_when_accessibility_text_is_longer(capture):
    capture.ax_text = SOURCE
    capture.copy_text = "every request"
    assert await native.capture_selection() == "every request"
    assert capture.copies == 1


@pytest.mark.parametrize("ax_text", ["Accessibility fallback", None])
async def test_no_fresh_copy_uses_accessibility_or_returns_none(capture, ax_text):
    capture.ax_text = ax_text
    capture.copy_text = None
    before = capture.pb.contents()
    assert await native.capture_selection() == ax_text
    assert capture.copies == 2
    assert capture.pb.contents() == before
    assert capture.pb.clears == 0  # Never use or restore unchanged, stale clipboard data.


@pytest.mark.parametrize("copied_items", [[], [{TEXT_TYPE: b"  \n  "}], [{"public.png": b"image"}]])
async def test_new_clipboard_without_usable_text_still_uses_accessibility(capture, copied_items):
    capture.ax_text = "Accessibility fallback"
    capture.on_copy = lambda: capture.pb.put(copied_items)
    before = capture.pb.contents()
    assert await native.capture_selection() == "Accessibility fallback"
    assert capture.copies == 1
    assert capture.pb.contents() == before


async def test_waits_for_delayed_clipboard_text_without_copying_again(capture):
    capture.ax_text = "Partial accessibility text"
    capture.on_copy = lambda: capture.pb.put([])

    def lazy_data():
        if capture.polls == 4:
            # A lazy provider supplies data without changing clipboard ownership.
            capture.pb.items = [PasteboardItem({TEXT_TYPE: SOURCE.encode("utf-8")})]

    capture.on_poll = lazy_data
    assert await native.capture_selection() == SOURCE
    assert capture.copies == 1 and capture.polls == 4


@pytest.mark.parametrize("restore", [True, False])
@pytest.mark.parametrize("original", [
    [],
    [{TEXT_TYPE: b"Old plain text", "public.html": b"<b>Old plain text</b>"}],
    [{"public.png": b"\x89PNG\x00\xff"}, {"custom.type": b"\x00\x01\x02"}],
])
async def test_clipboard_restoration_preserves_all_original_items_and_types(capture, restore, original):
    capture.pb.put(original)
    assert await native.capture_selection(restore=restore) == SOURCE
    expected = original if restore else [{TEXT_TYPE: SOURCE.encode("utf-8")}]
    assert capture.pb.contents() == expected
    assert capture.pb.clears == int(restore)


async def test_newer_user_copy_is_not_overwritten_by_restoration(capture):
    newer = [{TEXT_TYPE: b"User copied something else", "public.html": b"<p>New copy</p>"}]

    def concurrent_copy():
        if capture.copies:
            capture.pb.after_read = lambda: None
            capture.pb.put(newer)

    # Change ownership after reading the captured text, before restoration can run.
    capture.pb.after_read = concurrent_copy
    assert await native.capture_selection() == SOURCE
    assert capture.pb.contents() == newer
    assert capture.pb.clears == 0


async def test_cancelled_polling_restores_observed_clipboard_generation(capture):
    before = capture.pb.contents()
    capture.on_copy = lambda: capture.pb.put([])

    def cancel_after_observing_copy():
        if capture.polls == 2:
            raise asyncio.CancelledError()

    capture.on_poll = cancel_after_observing_copy
    await native.capture_selection()
    assert capture.copies == 1
    assert capture.pb.contents() == before
    assert capture.pb.clears == 1
