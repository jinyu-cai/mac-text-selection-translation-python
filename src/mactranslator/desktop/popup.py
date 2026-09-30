import AppKit as A
from PyObjCTools import AppHelper

from mactranslator.policies import can_save, first_usable, fit_frame
from . import widgets as W
from Foundation import NSUserDefaults
from .popup_cards import OutputCard, TopDownView, body_view, icon_button, spinner


class FloatingPanel(A.NSPanel):
    def canBecomeKeyWindow(self):
        return False

    def canBecomeMainWindow(self):
        return False


def screen_at(point):
    return next((s for s in A.NSScreen.screens() if A.NSPointInRect(point, s.frame())), A.NSScreen.mainScreen())


class FloatingIcon:
    def __init__(self, action):
        self.targets = []
        self.generation = 0
        self.point = None
        self.window = FloatingPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            A.NSMakeRect(0, 0, 32, 32), A.NSWindowStyleMaskBorderless | A.NSWindowStyleMaskNonactivatingPanel,
            A.NSBackingStoreBuffered, False)
        self.window.setReleasedWhenClosed_(False)
        self.window.setLevel_(A.NSFloatingWindowLevel)
        self.window.setHidesOnDeactivate_(False)
        self.window.setBecomesKeyOnlyIfNeeded_(True)
        self.window.setCollectionBehavior_(A.NSWindowCollectionBehaviorCanJoinAllSpaces |
                                           A.NSWindowCollectionBehaviorFullScreenAuxiliary)
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(A.NSColor.clearColor())
        self.window.setHasShadow_(False)
        button = W.button(self.window.contentView(), "T", 0, 1, 32, lambda _: self.activate(action), self.targets)
        image = W.symbol("textformat", "Translate Selection")
        if image:
            button.setImage_(image)
            button.setImagePosition_(A.NSImageOnly)
        button.setToolTip_("Translate Selection")
        button.setAccessibilityLabel_("Translate Selection")

    def activate(self, action):
        self.hide()
        action(self.point)

    def show(self, point):
        self.point = point
        self.generation += 1
        generation = self.generation
        screen = screen_at(point).visibleFrame()
        frame = fit_frame((point.x + 6, point.y - 6), (32, 32),
                          (screen.origin.x, screen.origin.y, screen.size.width, screen.size.height))
        self.window.setFrame_display_(A.NSMakeRect(*frame), True)
        self.window.orderFrontRegardless()
        AppHelper.callLater(5, lambda: self.hide() if generation == self.generation else None)

    def hide(self):
        self.generation += 1
        self.window.orderOut_(None)


class OutputPanel(A.NSPanel):
    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return False


class PopupDragView(A.NSView):
    def mouseDownCanMoveWindow(self):
        return False

    def mouseDown_(self, event):
        self.window().performWindowDragWithEvent_(event)


class ResizeHandle(A.NSView):
    def mouseDownCanMoveWindow(self):
        return False

    def resetCursorRects(self):
        self.addCursorRect_cursor_(self.bounds(), A.NSCursor.crosshairCursor())

    def mouseDown_(self, event):
        self.last_point = A.NSEvent.mouseLocation()

    def mouseDragged_(self, event):
        point = A.NSEvent.mouseLocation()
        self.owner.resize_by(point.x - self.last_point.x, point.y - self.last_point.y)
        self.last_point = point

    def mouseUp_(self, event):
        self.owner.remember_size()

    def drawRect_(self, dirty):
        A.NSColor.secondaryLabelColor().colorWithAlphaComponent_(0.65).setStroke()
        path = A.NSBezierPath.bezierPath()
        path.setLineWidth_(1.3)
        for i in range(3):
            offset = i * 4.5 + 5
            path.moveToPoint_(A.NSMakePoint(24 - offset, 4))
            path.lineToPoint_(A.NSMakePoint(20, offset))
        path.stroke()


class TranslationPopup:
    def __init__(self, app):
        self.app, self.targets = app, []
        self.request_id = None
        self.source = ""
        self.results = []
        self.dictionary = {}
        self.loading = False
        self.render_pending = False
        self.saved = False
        self.notice_text = None
        self.cards = {}
        self.defaults = NSUserDefaults.standardUserDefaults()
        width, height = self.defaults.doubleForKey_("popupWidth"), self.defaults.doubleForKey_("popupHeight")
        self.user_size = (width, height) if width > 0 and height > 0 else None
        self.window = OutputPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            A.NSMakeRect(0, 0, 360, 180), A.NSWindowStyleMaskBorderless | A.NSWindowStyleMaskNonactivatingPanel,
            A.NSBackingStoreBuffered, False)
        self.window.setReleasedWhenClosed_(False)
        self.window.setTitle_("Translation")
        self.window.setLevel_(A.NSFloatingWindowLevel)
        self.window.setHidesOnDeactivate_(False)
        self.window.setBecomesKeyOnlyIfNeeded_(True)
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(A.NSColor.clearColor())
        self.window.setHasShadow_(True)
        self.window.setCollectionBehavior_(A.NSWindowCollectionBehaviorCanJoinAllSpaces |
                                           A.NSWindowCollectionBehaviorFullScreenAuxiliary)
        self.content = A.NSVisualEffectView.alloc().initWithFrame_(A.NSMakeRect(0, 0, 360, 180))
        self.content.setMaterial_(A.NSVisualEffectMaterialPopover)
        self.content.setBlendingMode_(A.NSVisualEffectBlendingModeBehindWindow)
        self.content.setState_(A.NSVisualEffectStateActive)
        self.content.setWantsLayer_(True)
        self.content.layer().setCornerRadius_(14)
        self.content.layer().setMasksToBounds_(True)
        self.content.layer().setBorderWidth_(0.5)
        self.content.layer().setBorderColor_(A.NSColor.grayColor().colorWithAlphaComponent_(0.2).CGColor())
        self.window.setContentView_(self.content)
        self.header_icon = A.NSImageView.alloc().initWithFrame_(A.NSMakeRect(14, 14, 18, 18))
        self.header_icon.setImage_(W.symbol("textformat", "Translation"))
        self.header_icon.setContentTintColor_(A.NSColor.secondaryLabelColor())
        self.content.addSubview_(self.header_icon)
        self.title = W.label(self.content, "Translation", 40, 0, 170, 20)
        self.title.setFont_(A.NSFont.systemFontOfSize_weight_(13, A.NSFontWeightSemibold))
        self.title.setTextColor_(A.NSColor.secondaryLabelColor())
        self.progress = spinner(self.content)
        self.save_button = icon_button(self.content, "note.text.badge.plus", "Save Note",
                                       lambda _: self.save(), self.targets)
        self.close_button = icon_button(self.content, "xmark", "Close", lambda _: self.app.dismiss(), self.targets)
        self.divider = A.NSBox.alloc().initWithFrame_(A.NSMakeRect(14, 0, 332, 1))
        self.divider.setBoxType_(A.NSBoxSeparator)
        self.content.addSubview_(self.divider)
        self.scroll = A.NSScrollView.alloc().initWithFrame_(A.NSMakeRect(14, 14, 332, 112))
        self.scroll.setHasVerticalScroller_(True)
        self.scroll.setScrollerStyle_(A.NSScrollerStyleOverlay)
        self.scroll.setAutohidesScrollers_(True)
        self.scroll.setDrawsBackground_(False)
        self.scroll.setBorderType_(A.NSNoBorder)
        self.document = TopDownView.alloc().initWithFrame_(A.NSMakeRect(0, 0, 332, 112))
        self.scroll.setDocumentView_(self.document)
        self.content.addSubview_(self.scroll)
        self.source_card = OutputCard(app, source=True)
        self.document.addSubview_(self.source_card.view)
        self.notice_view = body_view(self.document)
        self.notice_view.setHidden_(True)
        self.drag_view = PopupDragView.alloc().initWithFrame_(A.NSMakeRect(0, 132, 256, 48))
        self.content.addSubview_(self.drag_view)
        self.resize_handle = ResizeHandle.alloc().initWithFrame_(A.NSMakeRect(336, 0, 24, 24))
        self.resize_handle.owner = self
        self.content.addSubview_(self.resize_handle)

    def show(self, text, request_id, point=None):
        self.request_id, self.source, self.saved = request_id, text, False
        self.results, self.dictionary, self.loading = [], {}, True
        self.notice_text = None
        point = point or A.NSEvent.mouseLocation()
        screen = screen_at(point).visibleFrame()
        size = self.user_size or (360, 180)
        width, height = max(300, min(900, size[0])), max(140, min(1000, size[1]))
        top = point.y - 12
        if top - height < screen.origin.y + 8:
            top = point.y + height + 12
        frame = fit_frame((point.x + 12, top), (width, height),
                          (screen.origin.x, screen.origin.y, screen.size.width, screen.size.height))
        self.window.setFrame_display_(A.NSMakeRect(*frame), True)
        self.scroll.contentView().scrollToPoint_(A.NSMakePoint(0, 0))
        self.render()
        self.window.orderFrontRegardless()

    def notice(self, text, point=None):
        self.show("", None, point)
        self.loading = False
        self.notice_text = text
        self.render()

    def hide(self):
        self.window.orderOut_(None)

    def refresh_speech(self):
        self.source_card.refresh_speech()
        for card in self.cards.values():
            card.refresh_speech()

    def _resize(self, width, height):
        current = self.window.frame()
        screen = (self.window.screen() or A.NSScreen.mainScreen()).visibleFrame()
        frame = fit_frame((current.origin.x, current.origin.y + current.size.height), (width, height),
                          (screen.origin.x, screen.origin.y, screen.size.width, screen.size.height))
        self.window.setFrame_display_(A.NSMakeRect(*frame), True)

    def resize_by(self, dx, dy):
        size = self.window.frame().size
        self.user_size = (max(300, min(900, size.width + dx)), max(140, min(1000, size.height - dy)))
        self._resize(*self.user_size)
        self.render()

    def remember_size(self):
        if self.user_size:
            size = self.window.frame().size
            self.user_size = (size.width, size.height)
            self.defaults.setDouble_forKey_(size.width, "popupWidth")
            self.defaults.setDouble_forKey_(size.height, "popupHeight")

    def event(self, event):
        if event["request_id"] != self.request_id:
            return
        kind = event["type"]
        if kind == "start":
            self.results = [{"id": p["id"], "name": p["name"], "output": "", "error": None, "loading": True}
                            for p in event["providers"] if p["kind"] in ("translation", "gemini_cli", "antigravity_cli", "codex_cli")]
        elif kind == "done":
            self.loading = False
        elif kind == "dictionary":
            data = event["data"]
            translations = data.get("translations", [])
            lines = ["### Microsoft Dictionary", data.get("displaySource", self.source)]
            for t in translations:
                lines.append(f"- **{t.get('displayTarget', '')}** · {t.get('posTag', '')}")
                back = [b.get("displayText", "") for b in t.get("backTranslations", [])]
                if back:
                    lines.append("  " + ", ".join(back))
            self.dictionary[event["provider_id"]] = "\n".join(lines)
        else:
            result = next((r for r in self.results if r["id"] == event.get("provider_id")), None)
            if result:
                if kind == "delta":
                    result["output"] += event.get("text", "")
                elif kind in ("provider_done", "provider_error"):
                    result["loading"] = False
                    if kind == "provider_error":
                        result["error"] = event.get("text", "Request failed")
            elif kind == "provider_error":
                self.dictionary[event["provider_id"]] = "Microsoft Dictionary: " + event.get("text", "Request failed")
        if not self.render_pending:
            self.render_pending = True
            AppHelper.callLater(0.04, self.render)

    def render(self):
        self.render_pending = False
        width = self.window.frame().size.width
        body_width = max(1, width - 28)
        origin = self.scroll.contentView().bounds().origin
        self.source_card.view.setHidden_(self.notice_text is not None)
        self.notice_view.setHidden_(self.notice_text is None)
        y = 0
        if self.notice_text is not None:
            self.notice_view.setString_(self.notice_text)
            self.notice_view.setFont_(A.NSFont.systemFontOfSize_(13))
            self.notice_view.setTextColor_(A.NSColor.systemOrangeColor())
            self.notice_view.setFrame_(A.NSMakeRect(0, 0, body_width, 24))
            container = self.notice_view.textContainer()
            container.setContainerSize_(A.NSMakeSize(body_width, 1e7))
            self.notice_view.layoutManager().ensureLayoutForTextContainer_(container)
            y = max(24, self.notice_view.layoutManager().usedRectForTextContainer_(container).size.height + 1)
            self.notice_view.setFrameSize_(A.NSMakeSize(body_width, y))
        else:
            self.source_card.update("", self.source)
            y = self.source_card.layout(body_width) + 12
        entries = [] if self.notice_text is not None else [
            (r["id"], r["name"], r["output"], r["loading"], r.get("error")) for r in self.results]
        if self.notice_text is None:
            entries.extend(("dictionary:" + key, "Microsoft Dictionary" if key != "error" else "Error",
                            value, False, value if key == "error" else None) for key, value in self.dictionary.items())
        keep = {entry[0] for entry in entries}
        for key in list(self.cards):
            if key not in keep:
                self.cards.pop(key).view.removeFromSuperview()
        for key, title, output, loading, error in entries:
            if key not in self.cards:
                self.cards[key] = OutputCard(self.app)
                self.document.addSubview_(self.cards[key].view)
            card = self.cards[key]
            card.update(title, output, loading, error)
            card.view.setFrameOrigin_(A.NSMakePoint(0, y))
            y += card.layout(body_width) + 12
        content_height = y + 14
        if self.user_size is None:
            self._resize(width, max(110, min(460, content_height + 62)))
        height = self.window.frame().size.height
        self.header_icon.setFrameOrigin_(A.NSMakePoint(14, height - 34))
        self.title.setFrame_(A.NSMakeRect(40, height - 36, max(1, width - 150), 20))
        self.close_button.setFrameOrigin_(A.NSMakePoint(width - 38, height - 38))
        self.save_button.setFrameOrigin_(A.NSMakePoint(width - 66, height - 38))
        self.progress.setFrameOrigin_(A.NSMakePoint(width - (88 if self.app.settings.enable_notes else 60), height - 34))
        (self.progress.startAnimation_ if self.loading else self.progress.stopAnimation_)(None)
        self.divider.setFrame_(A.NSMakeRect(14, height - 48, body_width, 1))
        self.scroll.setFrame_(A.NSMakeRect(14, 0, body_width, max(1, height - 60)))
        self.document.setFrameSize_(A.NSMakeSize(body_width, max(content_height, self.scroll.contentSize().height)))
        visible = self.scroll.contentView().bounds().size.height
        self.scroll.contentView().scrollToPoint_(A.NSMakePoint(0, min(origin.y, max(0, content_height - visible))))
        self.scroll.reflectScrolledClipView_(self.scroll.contentView())
        self.drag_view.setFrame_(A.NSMakeRect(0, height - 48, max(1, width - 104), 48))
        self.resize_handle.setFrameOrigin_(A.NSMakePoint(width - 24, 0))
        self.save_button.setHidden_(not self.app.settings.enable_notes or self.notice_text is not None)
        self.save_button.setEnabled_(not self.saved and bool(self.source) and can_save(self.results, self.loading))
        image = W.symbol("checkmark.circle.fill" if self.saved else "note.text.badge.plus", "Saved" if self.saved else "Save Note")
        if image:
            self.save_button.setImage_(image)
        self.save_button.setToolTip_("Saved" if self.saved else "Save Note")

    def failed(self, request_id, error):
        if request_id != self.request_id:
            return
        self.loading = False
        for result in self.results:
            if result["loading"]:
                result["loading"], result["error"] = False, str(error)
        if not self.results:
            self.dictionary["error"] = str(error)
        self.render()

    def save(self):
        if self.saved or not can_save(self.results, self.loading):
            return
        first = first_usable(self.results)
        body = {"source_text": self.source, "translated_text": first["output"] if first else None,
                "backend_name": first["name"] if first else None}
        request_id = self.request_id
        self.save_button.setEnabled_(False)

        def done(_):
            if request_id == self.request_id:
                self.saved = True
                self.render()
        self.app.request("POST", "/notes", json=body, done=done,
                         error=lambda exc: (self.render(), self.app.error(exc)))
