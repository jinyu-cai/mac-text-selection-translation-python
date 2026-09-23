import asyncio

import AppKit as A
from Foundation import NSObject
from PyObjCTools import AppHelper

from . import widgets as W
from .native import copy_text


class NoteObserver(NSObject):
    def textDidChange_(self, notification):
        self.owner.changed()


class NotesWindow:
    def __init__(self, app):
        self.app, self.targets = app, []
        self.notes = []
        self.current = None
        self.pending = {}
        self.writes = {}
        self.generations = {}
        self.loading = False
        self.window = W.window("本地笔记 · Python", 760, 620)
        root = self.window.contentView()
        self.selection = W.choice(root, [], 18, 565, 570, lambda _: self.select(), self.targets)
        W.button(root, "刷新", 610, 565, 126, lambda _: self.refresh(), self.targets)
        self.content, _ = W.text_area(root, 18, 260, 718, 293)
        W.label(root, "备注（自动保存）", 18, 229, 400)
        self.editor, _ = W.text_area(root, 18, 69, 718, 156, editable=True)
        self.observer = NoteObserver.alloc().init()
        self.observer.owner = self
        self.editor.setDelegate_(self.observer)
        self.status = W.label(root, "", 18, 15, 370, 28)
        W.button(root, "复制", 403, 15, 90, lambda _: self.copy(), self.targets)
        W.button(root, "保存备注", 506, 15, 110, lambda _: self.flush(), self.targets)
        W.button(root, "删除", 630, 15, 105, lambda _: self.delete(), self.targets)

    def show(self):
        self.refresh()
        self.window.makeKeyAndOrderFront_(None)
        A.NSApp.activateIgnoringOtherApps_(True)

    def refresh(self):
        self.flush()
        current = self.current

        async def fetch():
            if self.writes:
                await asyncio.gather(*(asyncio.wrap_future(f) for f in self.writes.values()))
            return await self.app.runtime.request("GET", "/notes")

        def done(notes):
            self.notes = notes
            self.selection.removeAllItems()
            self.selection.addItemsWithTitles_([f"{n['created_at'][:10]}  {n['source_text'][:60]}" for n in notes])
            if notes:
                index = next((i for i, n in enumerate(notes) if n["id"] == current), 0)
                self.selection.selectItemAtIndex_(index)
            self.select()
        self.app.run(fetch(), done=done)

    def select(self):
        self.flush()
        index = self.selection.indexOfSelectedItem()
        self.loading = True
        if not 0 <= index < len(self.notes):
            self.current = None
            self.content.setString_("还没有笔记。在翻译浮窗中点击「保存笔记」。")
            self.editor.setString_("")
            self.editor.setEditable_(False)
        else:
            note = self.notes[index]
            self.current = note["id"]
            self.content.textStorage().setAttributedString_(W.attributed_markdown(
                f"### 原文\n{note['source_text']}\n\n### {note.get('backend_name') or '译文'}\n"
                f"{note.get('translated_text') or ''}"))
            self.editor.setString_(note["user_note"])
            self.editor.setEditable_(True)
        self.loading = False

    def changed(self):
        if self.loading or not self.current:
            return
        note_id = self.current
        self.pending[note_id] = str(self.editor.string())
        for note in self.notes:
            if note["id"] == note_id:
                note["user_note"] = self.pending[note_id]
        self.generations[note_id] = self.generations.get(note_id, 0) + 1
        generation = self.generations[note_id]
        self.status.setStringValue_("尚未保存…")
        AppHelper.callLater(0.5, lambda: self.flush() if self.generations.get(note_id) == generation else None)

    def flush(self):
        for note_id, text in list(self.pending.items()):
            previous = self.writes.get(note_id)
            generation = self.generations.get(note_id, 0)

            async def save(note_id=note_id, text=text, previous=previous):
                if previous:
                    try:
                        await asyncio.wrap_future(previous)
                    except Exception:
                        pass
                return await self.app.runtime.request("PATCH", f"/notes/{note_id}", json={"user_note": text})

            def done(note, generation=generation):
                for i, old in enumerate(self.notes):
                    if old["id"] == note["id"]:
                        if self.generations.get(note["id"], 0) != generation:
                            note["user_note"] = old["user_note"]
                        self.notes[i] = note
                if self.generations.get(note["id"], 0) == generation:
                    self.status.setStringValue_("已保存")

            def failed(exc, note_id=note_id, text=text):
                self.pending.setdefault(note_id, text)
                self.status.setStringValue_("保存失败：" + str(exc))

            self.writes[note_id] = self.app.run(save(), done=done, error=failed, during_quit=True)
            self.pending.pop(note_id, None)
        return list(self.writes.values())

    def copy(self):
        note = next((n for n in self.notes if n["id"] == self.current), None)
        if note:
            copy_text(note["source_text"] + "\n\n" + (note["translated_text"] or "") + "\n\n" + str(self.editor.string()))

    def delete(self):
        if not self.current:
            return
        note_id = self.current
        self.flush()
        previous = self.writes.get(note_id)

        async def delete():
            if previous:
                await asyncio.wrap_future(previous)
            return await self.app.runtime.request("DELETE", f"/notes/{note_id}")

        def done(_):
            self.writes.pop(note_id, None)
            self.pending.pop(note_id, None)
            self.current = None
            self.refresh()
        self.app.run(delete(), done=done)
