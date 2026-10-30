"""Native text-layout regressions using cards and a window that stays hidden."""
from types import SimpleNamespace

import pytest

A = pytest.importorskip("AppKit")

from mactranslator.desktop.popup import TranslationPopup  # noqa: E402
from mactranslator.desktop.popup_cards import OutputCard  # noqa: E402


SOURCE = (
    "🧪 Agentero evaluation notes\n\n"
    + "Test requests that should be refused, together with ordinary tasks. " * 12
    + "\n\n✅ Include both allowed requests and disallowed requests. "
    "Use emoji 👩🏽‍💻, 中文, café, and xᵢ when checking text layout. "
    "These catch models that simply comply with every request."
)
WIDTHS = [300, 680, 900, 300, 900, 680]


@pytest.fixture(scope="module", autouse=True)
def native_application():
    # NSTextView font/layout initialization needs an application, but no window
    # is shown and no activation, accessibility, or clipboard APIs are used.
    return A.NSApplication.sharedApplication()


def application():
    return SimpleNamespace(settings=SimpleNamespace(providers=[], enable_notes=False,
                                                    enable_word_suggestions=False),
                           speak=lambda _: None)


def assert_complete_layout(card, source):
    assert str(card.text.string()) == source
    length = len(source.encode("utf-16-le")) // 2
    assert card.text.textStorage().length() == length
    manager, container = card.text.layoutManager(), card.text.textContainer()
    glyphs = manager.glyphRangeForTextContainer_(container)
    assert tuple(glyphs) == (0, manager.numberOfGlyphs())
    characters, _ = manager.characterRangeForGlyphRange_actualGlyphRange_(glyphs, None)
    assert tuple(characters) == (0, length)
    used = manager.usedRectForTextContainer_(container)
    ink = manager.boundingRectForGlyphRange_inTextContainer_(glyphs, container)
    last = manager.boundingRectForGlyphRange_inTextContainer_((glyphs.length - 1, 1), container)
    assert A.NSMaxY(used) <= card.text.bounds().size.height
    assert A.NSMaxY(ink) <= card.text.bounds().size.height
    assert A.NSMaxY(last) <= card.text.bounds().size.height
    assert A.NSMaxX(last) <= card.text.bounds().size.width
    assert A.NSMaxY(card.text.frame()) <= card.view.bounds().size.height


@pytest.mark.parametrize("source", [SOURCE, (SOURCE + "\n\n") * 16 + SOURCE])
def test_source_card_lays_out_entire_text_after_repeated_resize(source):
    card = OutputCard(application(), source=True)
    for width in WIDTHS:
        card.update("", source)
        card.layout(width)
        assert_complete_layout(card, source)


def test_popup_render_keeps_complete_source_above_results():
    popup = TranslationPopup(application())
    popup.source = SOURCE
    popup.results = [{"id": "result", "name": "Test", "output": "Translation.",
                      "loading": False, "error": None}]
    try:
        for width in WIDTHS:
            popup.user_size = (width, 400)
            popup.window.setFrame_display_(A.NSMakeRect(0, 0, width, 400), False)
            popup.results[0]["output"] += " More output."
            popup.render()
            assert not popup.window.isVisible()
            assert_complete_layout(popup.source_card, SOURCE)
            source_bottom = A.NSMaxY(popup.source_card.view.frame())
            assert popup.cards["result"].view.frame().origin.y >= source_bottom
            assert popup.document.bounds().size.height >= source_bottom
            clip = popup.scroll.contentView()
            clip.scrollToPoint_(A.NSMakePoint(0, max(0, source_bottom - clip.bounds().size.height)))
            assert A.NSMaxY(clip.bounds()) >= source_bottom
    finally:
        popup.window.close()
