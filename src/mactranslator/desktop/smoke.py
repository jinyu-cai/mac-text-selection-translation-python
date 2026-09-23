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


def run(output_directory, app_factory):
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyAccessory)
    app.finishLaunching()
    owner = app_factory()
    owner.settings = Settings(enable_notes=True, providers=[Provider(name="示例翻译后端")])
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
    render(settings.window, "settings-general.png")
    tabs = next(v for v in settings.window.contentView().subviews() if isinstance(v, A.NSTabView))
    tabs.selectTabViewItemAtIndex_(1)
    render(settings.window, "settings-providers.png")
    notes.notes = [{"id": str(uuid4()), "source_text": "Hello", "translated_text": "你好", "backend_name": "示例",
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
    owner.hotkeys.stop()
    owner.hotkeys.configure([(Hotkey(key_code=111, modifiers=(1 << 18) | (1 << 19) | (1 << 20)), lambda: None)])
    owner.hotkeys.stop()
    owner.watcher.stop()
    A.NSEvent.removeMonitor_(owner.monitor)
    # Drain UI work scheduled by the streaming renderer before releasing controllers.
    A.NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
    report = {"native_windows": True, "ocr": recognized, "backend_lifecycle": True,
              "screenshots": ["translation.png", "settings-general.png", "settings-providers.png", "notes.png"]}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False), flush=True)
