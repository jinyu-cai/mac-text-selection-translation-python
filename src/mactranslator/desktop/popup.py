import AppKit as A
from PyObjCTools import AppHelper

from mactranslator.policies import can_save, first_usable, fit_frame
from . import widgets as W
from .native import copy_text


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
        self.window.setBackgroundColor_(A.NSColor.windowBackgroundColor())
        W.button(self.window.contentView(), "译", 0, 1, 32, lambda _: self.activate(action), self.targets)

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
        self.window = A.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            A.NSMakeRect(0, 0, 610, 460), A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable,
            A.NSBackingStoreBuffered, False)
        self.window.setReleasedWhenClosed_(False)
        self.window.setTitle_("翻译")
        self.window.setLevel_(A.NSFloatingWindowLevel)
        self.window.setHidesOnDeactivate_(False)
        self.window.setMovableByWindowBackground_(True)
        self.window.setCollectionBehavior_(A.NSWindowCollectionBehaviorCanJoinAllSpaces |
                                           A.NSWindowCollectionBehaviorFullScreenAuxiliary)
        content = self.window.contentView()
        self.text, self.scroll = W.text_area(content, 12, 56, 586, 392)
        self.scroll.setAutoresizingMask_(A.NSViewWidthSizable | A.NSViewHeightSizable)
        self.selection = W.choice(content, ["原文"], 12, 15, 185)
        W.button(content, "复制", 202, 14, 60, lambda _: copy_text(self.selected_text()), self.targets)
        self.speak = W.button(content, "朗读", 266, 14, 60, lambda _: self.app.speak(self.selected_text()), self.targets)
        W.button(content, "停止", 330, 14, 60, lambda _: self.app.stop_speech(), self.targets)
        self.save_button = W.button(content, "保存笔记", 394, 14, 100, lambda _: self.save(), self.targets)
        W.button(content, "关闭", 508, 14, 76, lambda _: self.app.dismiss(), self.targets)

    def show(self, text, request_id, point=None):
        self.request_id, self.source, self.saved = request_id, text, False
        self.results, self.dictionary, self.loading = [], {}, True
        self.selection.removeAllItems()
        self.selection.addItemWithTitle_("原文")
        self.render()
        point = point or A.NSEvent.mouseLocation()
        screen = screen_at(point).visibleFrame()
        top = point.y - 12
        if top - 460 < screen.origin.y + 8:
            top = point.y + 472
        frame = fit_frame((point.x + 12, top), (610, 484),
                          (screen.origin.x, screen.origin.y, screen.size.width, screen.size.height))
        self.window.setFrame_display_(A.NSMakeRect(*frame), True)
        self.window.makeKeyAndOrderFront_(None)

    def notice(self, text, point=None):
        self.show("", None, point)
        self.loading = False
        self.text.setString_(text)
        self.save_button.setEnabled_(False)

    def hide(self):
        self.window.orderOut_(None)

    def selected_text(self):
        index = self.selection.indexOfSelectedItem()
        if index <= 0:
            return self.source
        if index <= len(self.results):
            return self.results[index - 1]["output"]
        values = list(self.dictionary.values())
        dictionary_index = index - 1 - len(self.results)
        return values[dictionary_index] if 0 <= dictionary_index < len(values) else self.source

    def event(self, event):
        if event["request_id"] != self.request_id:
            return
        kind = event["type"]
        if kind == "start":
            self.results = [{"id": p["id"], "name": p["name"], "output": "", "error": None, "loading": True}
                            for p in event["providers"] if p["kind"] == "translation"]
            self.selection.removeAllItems()
            self.selection.addItemsWithTitles_(["原文"] + [r["name"] for r in self.results])
            if self.results:
                self.selection.selectItemAtIndex_(1)
        elif kind == "done":
            self.loading = False
        elif kind == "dictionary":
            data = event["data"]
            translations = data.get("translations", [])
            lines = ["### 微软词典", data.get("displaySource", self.source)]
            for t in translations:
                lines.append(f"- **{t.get('displayTarget', '')}** · {t.get('posTag', '')}")
                back = [b.get("displayText", "") for b in t.get("backTranslations", [])]
                if back:
                    lines.append("  " + ", ".join(back))
            self.dictionary[event["provider_id"]] = "\n".join(lines)
            self.selection.addItemWithTitle_("微软词典")
        else:
            result = next((r for r in self.results if r["id"] == event.get("provider_id")), None)
            if result:
                if kind == "delta":
                    result["output"] += event.get("text", "")
                elif kind in ("provider_done", "provider_error"):
                    result["loading"] = False
                    if kind == "provider_error":
                        result["error"] = event.get("text", "请求失败")
            elif kind == "provider_error":
                self.dictionary[event["provider_id"]] = "微软词典：" + event.get("text", "请求失败")
        if not self.render_pending:
            self.render_pending = True
            AppHelper.callLater(0.04, self.render)

    def render(self):
        self.render_pending = False
        sections = ["### 原文\n" + self.source]
        for result in self.results:
            status = " · 翻译中…" if result["loading"] else ""
            sections.append(f"### {result['name']}{status}\n{result['output']}")
            if result.get("error"):
                sections.append("错误：" + result["error"])
        sections.extend(self.dictionary.values())
        if self.loading and not self.results:
            sections.append("正在请求…")
        origin = self.scroll.contentView().bounds().origin
        self.text.textStorage().setAttributedString_(W.attributed_markdown("\n\n".join(sections)))
        self.scroll.contentView().scrollToPoint_(origin)
        self.scroll.reflectScrolledClipView_(self.scroll.contentView())
        self.save_button.setHidden_(not self.app.settings.enable_notes)
        self.save_button.setEnabled_(not self.saved and bool(self.source) and can_save(self.results, self.loading))
        self.save_button.setTitle_("已保存" if self.saved else "保存笔记")

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
