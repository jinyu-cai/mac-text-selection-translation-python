"""Opt-in packaged-app smoke check. Uses temporary data, synthetic text, and no provider keys."""
import json
import tempfile
from pathlib import Path
from uuid import uuid4

import AppKit as A
import Quartz as Q
from Foundation import NSDate

from mactranslator.contracts import Hotkey, Provider, Settings
from .notes import NotesWindow
from .ocr import OCRCapture
from .runtime import BackendRuntime
from .settings import SettingsWindow
from .native import snapshot_clipboard
from mactranslator.presets import google_ai_studio_provider


def run(output_directory, app_factory):
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyAccessory)
    app.finishLaunching()
    owner = app_factory()
    owner.settings = Settings(enable_notes=True, providers=[Provider(name="Example Translator")])
    settings = SettingsWindow(owner)
    notes = NotesWindow(owner)

    def render(window, filename):
        window.orderFront_(None)
        A.NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
        view = window.contentView()
        view.layoutSubtreeIfNeeded()
        view.displayIfNeeded()
        bitmap = view.bitmapImageRepForCachingDisplayInRect_(view.bounds())
        previous = A.NSAppearance.currentAppearance()
        A.NSAppearance.setCurrentAppearance_(window.effectiveAppearance())
        try:
            view.cacheDisplayInRect_toBitmapImageRep_(view.bounds(), bitmap)
            # NSWindow paints its background outside contentView. Composite the
            # cached transparent view onto that background for readable diagnostic renders.
            canvas = A.NSImage.alloc().initWithSize_(view.bounds().size)
            canvas.lockFocus()
            window.backgroundColor().setFill()
            A.NSRectFill(view.bounds())
            bitmap.drawInRect_(view.bounds())
            canvas.unlockFocus()
            bitmap = A.NSBitmapImageRep.imageRepWithData_(canvas.TIFFRepresentation())
        finally:
            A.NSAppearance.setCurrentAppearance_(previous)
        data = bitmap.representationUsingType_properties_(A.NSBitmapImageFileTypePNG, {})
        data.writeToFile_atomically_(str(output / filename), True)
        window.orderOut_(None)

    request_id = str(uuid4())
    p = owner.settings.providers[0]
    owner.popup.show("A small step toward a native Python application.", request_id)
    owner.popup.event({"type": "start", "request_id": request_id, "providers": [p.model_dump(mode="json")]})
    owner.popup.event({"type": "delta", "request_id": request_id, "provider_id": str(p.id),
                       "text": "朝着原生 Python 应用迈出的一小步。\n\n| 词语 | 含义 |\n|---|---|\n| native | 原生 |"})
    owner.popup.event({"type": "provider_done", "request_id": request_id, "provider_id": str(p.id)})
    owner.popup.event({"type": "done", "request_id": request_id})
    owner.popup.render()
    render(owner.popup.window, "translation.png")
    for appearance, filename in ((A.NSAppearanceNameAqua, "translation-light.png"),
                                 (A.NSAppearanceNameDarkAqua, "translation-dark.png")):
        owner.popup.window.setAppearance_(A.NSAppearance.appearanceNamed_(appearance))
        render(owner.popup.window, filename)
    owner.popup.window.setAppearance_(None)
    render(settings.window, "settings-general.png")
    tabs = next(v for v in settings.window.contentView().subviews() if isinstance(v, A.NSTabView))
    tabs.selectTabViewItemAtIndex_(1)
    render(settings.window, "settings-providers.png")
    settings.add(google_ai_studio_provider())
    assert settings.fields["voice"].isHidden()
    assert not settings.reasoning.isHidden()
    render(settings.window, "settings-google.png")
    settings.kind.selectItemAtIndex_(settings.kinds.index("antigravity_cli"))
    settings.kind_changed()
    assert not settings.fields["cli_path"].isHidden()
    assert not settings.key.isEnabled()
    assert not settings.fields["endpoint"].isEnabled()
    assert settings.reasoning.isHidden()
    render(settings.window, "settings-antigravity-cli.png")
    from .antigravity_account import AntigravityAccountWindow
    account = AntigravityAccountWindow(settings)
    account.update({"status": "ready", "message": "Connected. Choose a model below.",
                    "models": [{"id": "gemini-example-medium", "name": "Gemini Example"}]})
    assert account.use.isEnabled()
    render(account.window, "antigravity-account.png")
    account.closed = True
    settings.kind.selectItemAtIndex_(settings.kinds.index("codex_cli"))
    settings.kind_changed()
    assert not settings.account_button.isHidden()
    assert not settings.codex_reasoning.isHidden()
    settings.codex_reasoning.selectItemWithTitle_("high")
    settings.collect_provider()
    assert settings.draft["providers"][settings.index]["reasoning"] == "high"
    assert str(settings.fields["cli_path"].stringValue()) == "codex"
    assert not settings.key.isEnabled()
    render(settings.window, "settings-codex.png")
    from .codex_account import CodexAccountWindow
    codex_account = CodexAccountWindow(settings)
    codex_account.update({"status": "ready", "message": "Connected to ChatGPT. Choose a model below.",
                          "models": [{"id": "example-model", "name": "Example Model", "efforts": ["low", "high"]}]})
    assert codex_account.use.isEnabled()
    assert list(codex_account.effort.itemTitles()) == ["auto", "low", "high"]
    codex_account.effort.selectItemWithTitle_("low")
    assert codex_account.selection_options() == {"reasoning": "low"}
    assert codex_account.code.isHidden()
    render(codex_account.window, "codex-account.png")
    codex_account.closed = True
    settings.kind.selectItemAtIndex_(settings.kinds.index("openai_tts"))
    settings.kind_changed()
    assert not settings.fields["voice"].isHidden()
    assert settings.reasoning.isHidden()
    render(settings.window, "settings-speech.png")
    settings.kind.selectItemAtIndex_(settings.kinds.index("translation"))
    settings.kind_changed()

    # Exercise actual responder-chain shortcuts, including the secure field editor.
    # Preserve clipboard data, and never overwrite a concurrent user copy on cleanup.
    pasteboard = A.NSPasteboard.generalPasteboard()
    saved_clipboard = snapshot_clipboard()
    generation = None
    try:
        pasteboard.clearContents()
        pasteboard.setString_forType_("synthetic-paste-key", A.NSPasteboardTypeString)
        generation = pasteboard.changeCount()
        settings.show()
        # NSRunLoop alone does not dispatch the activation event to NSApplication.
        deadline = NSDate.dateWithTimeIntervalSinceNow_(2)
        while app.keyWindow() != settings.window and deadline.timeIntervalSinceNow() > 0:
            event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
                A.NSEventMaskAny, NSDate.dateWithTimeIntervalSinceNow_(0.05), A.NSDefaultRunLoopMode, True)
            if event:
                app.sendEvent_(event)
            app.updateWindows()
        assert app.keyWindow() == settings.window

        def shortcut(character, keycode):
            event = A.NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
                A.NSEventTypeKeyDown, A.NSMakePoint(0, 0), A.NSEventModifierFlagCommand, 0,
                settings.window.windowNumber(), None, character, character, False, keycode)
            assert app.mainMenu().performKeyEquivalent_(event), f"Shortcut failed: {character}"

        for field in (settings.name, settings.key):
            field.setStringValue_("replace me")
            settings.window.makeFirstResponder_(field)
            shortcut("a", 0)
            shortcut("v", 9)
            settings.window.makeFirstResponder_(None)
            assert str(field.stringValue()) == "synthetic-paste-key"
        settings.clear_key.setState_(1)
        settings.paste_key()
        assert not settings.clear_key.state()
        assert str(settings.key.stringValue()) == "synthetic-paste-key"
    finally:
        if generation is not None and pasteboard.changeCount() == generation:
            pasteboard.clearContents()
            if saved_clipboard:
                pasteboard.writeObjects_(saved_clipboard)
        settings.key.setStringValue_("")
        settings.window.orderOut_(None)
    notes.notes = [{"id": str(uuid4()), "source_text": "Hello", "translated_text": "你好", "backend_name": "Example",
                    "user_note": "This is a local note.", "created_at": "2026-09-19T00:00:00Z"}]
    notes.selection.addItemWithTitle_("Hello")
    notes.select()
    render(notes.window, "notes.png")

    # Exercise Vision against a generated image; no screen capture or user content is accessed.
    image = A.NSImage.alloc().initWithSize_(A.NSMakeSize(800, 160))
    image.lockFocus()
    A.NSColor.whiteColor().setFill()
    A.NSRectFill(A.NSMakeRect(0, 0, 800, 160))
    from Foundation import NSString
    NSString.stringWithString_("Hello Python translator").drawAtPoint_withAttributes_(
        A.NSMakePoint(25, 60), {A.NSFontAttributeName: A.NSFont.systemFontOfSize_(38),
                               A.NSForegroundColorAttributeName: A.NSColor.blackColor()})
    image.unlockFocus()
    source = Q.CGImageSourceCreateWithData(image.TIFFRepresentation(), None)
    recognized = OCRCapture.recognize(Q.CGImageSourceCreateImageAtIndex(source, 0, None))
    assert "Hello" in recognized and "Python" in recognized, recognized

    class NoCredentials:
        def get(self, account):
            return ""

        def set(self, account, value):
            raise AssertionError("Smoke check must not access Keychain")

    with tempfile.TemporaryDirectory(prefix="translator-smoke-") as temp:
        runtime = BackendRuntime(Path(temp) / "test.sqlite3", NoCredentials())
        try:
            assert runtime.start().result(10)["ready"]
            data = runtime.submit(runtime.request("GET", "/settings")).result(5)
            assert data["providers"] == []
        finally:
            runtime.stop()
        assert not runtime.thread.is_alive()
    check_popup_controls()
    owner.hotkeys.stop()
    owner.hotkeys.configure([(Hotkey(key_code=111, modifiers=(1 << 18) | (1 << 19) | (1 << 20)), lambda: None)])
    owner.hotkeys.stop()
    owner.watcher.stop()
    A.NSEvent.removeMonitor_(owner.monitor)
    # Drain UI work scheduled by the streaming renderer before releasing controllers.
    A.NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
    report = {"native_windows": True, "ocr": recognized, "backend_lifecycle": True, "native_paste": True, "popup_cards": True,
              "screenshots": ["translation.png", "settings-general.png", "settings-providers.png",
                              "settings-google.png", "settings-antigravity-cli.png", "settings-speech.png", "notes.png"]}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False), flush=True)


def check_popup_controls():
    """Exercise independent card actions and layout without speech/network requests."""
    from types import SimpleNamespace
    from .popup import TranslationPopup
    from . import popup_cards

    spoken, copied = [], []
    owner = SimpleNamespace(settings=Settings(enable_notes=True), speak=spoken.append, dismiss=lambda: None)
    popup = TranslationPopup(owner)
    popup.user_size = None
    request_id = str(uuid4())
    first, second = Provider(name="First"), Provider(name="Second")
    popup.show("Hello, world.", request_id)
    popup.event({"type": "start", "request_id": request_id,
                 "providers": [p.model_dump(mode="json") for p in (first, second)]})
    for provider, output in ((first, "Hello."), (second, "Bonjour.")):
        popup.event({"type": "delta", "request_id": request_id, "provider_id": str(provider.id), "text": output})
    popup.render()
    original_copy = popup_cards.copy_text
    try:
        popup_cards.copy_text = copied.append
        popup.source_card.speak.performClick_(None)
        popup.cards[str(first.id)].speak.performClick_(None)
        popup.cards[str(second.id)].copy.performClick_(None)
        assert spoken == ["Hello, world.", "Hello."]
        assert copied == ["Bonjour."]
        old_card = popup.cards[str(first.id)]
        popup.render()
        assert popup.cards[str(first.id)] is old_card
        short_height = popup.window.frame().size.height
        popup.event({"type": "delta", "request_id": request_id, "provider_id": str(second.id),
                     "text": "\nA long paragraph to check wrapping and scrolling. " * 100})
        popup.render()
        assert short_height < popup.window.frame().size.height <= 460
        assert popup.document.frame().size.height > popup.scroll.contentSize().height
        popup.resize_by(140, -120)
        manual_size = popup.window.frame().size
        popup.event({"type": "delta", "request_id": request_id, "provider_id": str(second.id), "text": " More."})
        popup.render()
        assert popup.window.frame().size == manual_size
        owner.settings = Settings(providers=[Provider(kind="openai_tts")])
        owner.speech_preparing = True
        popup.refresh_speech()
        assert popup.cards[str(first.id)].speak.isHidden()
        owner.speech_preparing = False
        popup.refresh_speech()
        assert not popup.cards[str(first.id)].speak.isHidden()
        popup.notice("Test notice")
        assert popup.notice_text == "Test notice" and not popup.cards
        assert popup.save_button.isHidden()
    finally:
        popup_cards.copy_text = original_copy
        popup.hide()
