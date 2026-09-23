import copy

import AppKit as A

from mactranslator.contracts import Hotkey, Provider, Settings
from mactranslator.policies import TEMPLATE, move
from . import widgets as W
from .native import login_status, set_login


def shortcut_label(hotkey):
    flags = hotkey["modifiers"]
    prefix = "".join(symbol for flag, symbol in ((1 << 18, "⌃"), (1 << 19, "⌥"),
                                                 (1 << 17, "⇧"), (1 << 20, "⌘")) if flags & flag)
    from .keycodes import KEY_NAMES
    return prefix + KEY_NAMES.get(hotkey["key_code"], f"键 {hotkey['key_code']}")


class SettingsWindow:
    def __init__(self, app):
        self.app, self.targets = app, []
        self.window = W.window("设置 · Python", 850, 700)
        self.draft = app.settings.model_dump(mode="json")
        self.index = None
        self.recording = None
        root = self.window.contentView()
        tabs = A.NSTabView.alloc().initWithFrame_(A.NSMakeRect(16, 58, 818, 626))
        root.addSubview_(tabs)
        for title, build in (("通用", self.build_general), ("翻译 / TTS 后端", self.build_providers)):
            tab = A.NSTabViewItem.alloc().initWithIdentifier_(title)
            tab.setLabel_(title)
            view = A.NSView.alloc().initWithFrame_(A.NSMakeRect(0, 0, 790, 580))
            tab.setView_(view)
            tabs.addTabViewItem_(tab)
            build(view)
        self.status = W.label(root, "", 20, 15, 590, 28)
        W.button(root, "取消", 620, 15, 90, lambda _: self.close(), self.targets)
        self.save_button = W.button(root, "保存", 730, 15, 95, lambda _: self.save(), self.targets)

    def reload(self):
        self.draft = self.app.settings.model_dump(mode="json")
        for key, view in self.checks.items():
            view.setState_(self.draft[key])
        self.language.setStringValue_(self.draft["target_language"])
        self.prompt.setString_(self.draft["custom_prompt"])
        for key, view in self.hotkey_buttons.items():
            view.setTitle_(shortcut_label(self.draft[key]))
        from ServiceManagement import SMAppServiceStatusEnabled, SMAppServiceStatusRequiresApproval
        self.login.setState_(login_status() in (SMAppServiceStatusEnabled, SMAppServiceStatusRequiresApproval))
        self.refresh_list()
        self.status.setStringValue_("")

    def build_general(self, parent):
        self.checks = {}
        options = [("enable_hotkey", "启用划词快捷键"), ("enable_ocr_hotkey", "启用截图 OCR 快捷键"),
                   ("enable_floating_icon", "选中文字后显示浮标"), ("restore_clipboard", "取词后恢复剪贴板"),
                   ("enable_notes", "启用本地笔记")]
        for i, (key, title) in enumerate(options):
            self.checks[key] = W.check(parent, title, 18, 536 - i * 36, 340, self.draft[key])
        self.hotkey_buttons = {}
        for key, y in (("hotkey", 534), ("ocr_hotkey", 498)):
            self.hotkey_buttons[key] = W.button(parent, shortcut_label(self.draft[key]), 385, y, 190,
                                                lambda _, key=key: self.record(key), self.targets)
        W.label(parent, "点击按钮录制快捷键；Esc 取消", 390, 459, 340)
        from ServiceManagement import SMAppServiceStatusEnabled, SMAppServiceStatusRequiresApproval
        self.login = W.check(parent, "开机自启动（打包应用）", 18, 349, 345,
                             login_status() in (SMAppServiceStatusEnabled, SMAppServiceStatusRequiresApproval))
        W.label(parent, "目标语言", 18, 307, 110)
        self.language = W.field(parent, 125, 305, 220, self.draft["target_language"])
        W.label(parent, "自定义提示词（留空使用内置三功能模板）", 18, 259, 430)
        W.button(parent, "使用三功能模板", 535, 258, 205,
                 lambda _: self.prompt.setString_(TEMPLATE), self.targets)
        self.prompt, _ = W.text_area(parent, 18, 35, 722, 218, editable=True)
        self.prompt.setString_(self.draft["custom_prompt"])

    def build_providers(self, parent):
        self.provider_choice = W.choice(parent, [], 18, 532, 726, lambda _: self.select(), self.targets)
        for title, x, action in (("添加", 18, self.add), ("删除", 110, self.remove),
                                 ("上移", 202, lambda: self.reorder(-1)), ("下移", 294, lambda: self.reorder(1))):
            W.button(parent, title, x, 490, 86, lambda _, action=action: action(), self.targets)
        self.enabled = W.check(parent, "启用", 415, 494, 100)
        self.kinds = ["translation", "openai_tts", "dashscope_tts"]
        kind_names = ["AI 翻译", "OpenAI 兼容 TTS", "DashScope TTS"]
        if self.app.experimental:
            self.kinds.append("dictionary")
            kind_names.append("微软词典（实验）")
        W.label(parent, "类型", 18, 449, 100)
        self.kind = W.choice(parent, kind_names, 128, 447, 250, lambda _: self.kind_changed(), self.targets)
        W.label(parent, "名称", 404, 449, 75)
        self.name = W.field(parent, 475, 447, 269)
        self.fields = {}
        for name, title, y in (("endpoint", "接口地址", 403), ("model", "模型", 362),
                               ("voice", "TTS 音色", 237), ("instructions", "TTS 风格", 155)):
            W.label(parent, title, 18, y + 2, 105)
            self.fields[name] = W.field(parent, 128, y, 616)
        W.label(parent, "API Key", 18, 323, 105)
        self.key = W.field(parent, 128, 321, 450, secure=True)
        self.clear_key = W.check(parent, "清除 Key", 595, 322, 150)
        W.label(parent, "思考能力", 18, 281, 105)
        self.reasoning = W.choice(parent, ["auto", "off", "low", "medium", "high", "xhigh", "max"], 128, 278, 250)
        W.label(parent, "TTS 格式", 18, 197, 105)
        self.format = W.choice(parent, ["mp3", "opus", "aac", "flac", "wav", "pcm"], 128, 195, 250)
        W.label(parent, "词典地域", 18, 116, 105)
        self.region = W.field(parent, 128, 114, 175)
        W.label(parent, "原语言", 316, 116, 65)
        self.from_language = W.field(parent, 386, 114, 115)
        W.label(parent, "目标语言", 511, 116, 100)
        self.to_language = W.field(parent, 616, 114, 128)
        self.test_button = W.button(parent, "保存并测试连接 / 朗读", 18, 58, 270, lambda _: self.test(), self.targets)
        W.label(parent, "列表顺序决定翻译卡片和朗读菜单顺序；类型无关的字段将忽略。", 18, 20, 730)
        self.refresh_list()

    def refresh_list(self, index=None):
        self.provider_choice.removeAllItems()
        providers = self.draft["providers"]
        self.provider_choice.addItemsWithTitles_([f"{i + 1}. {p['name']}" for i, p in enumerate(providers)])
        self.index = min(index if index is not None else (self.index or 0), len(providers) - 1) if providers else None
        if self.index is not None:
            self.provider_choice.selectItemAtIndex_(self.index)
        self.load_provider()

    def load_provider(self):
        p = self.draft["providers"][self.index] if self.index is not None else Provider().model_dump(mode="json")
        self.name.setStringValue_(p["name"] if self.index is not None else "请添加后端")
        self.kind.selectItemAtIndex_(self.kinds.index(p["kind"]) if p["kind"] in self.kinds else 0)
        self.enabled.setState_(p["enabled"])
        for key, view in self.fields.items():
            view.setStringValue_(p[key])
        self.key.setStringValue_(p.get("api_key", ""))
        self.key.setPlaceholderString_("已保存；留空保持不变" if p.get("has_api_key") else "本地服务可留空")
        self.clear_key.setState_(0)
        self.reasoning.selectItemWithTitle_(p["reasoning"])
        self.format.selectItemWithTitle_(p["response_format"])
        self.region.setStringValue_(p["region"])
        self.from_language.setStringValue_(p["from_language"])
        self.to_language.setStringValue_(p["to_language"])
        self.test_button.setEnabled_(self.index is not None)

    def collect_provider(self):
        if self.index is None:
            return
        p = self.draft["providers"][self.index]
        p.update(name=str(self.name.stringValue()), kind=self.kinds[self.kind.indexOfSelectedItem()],
                 enabled=bool(self.enabled.state()), reasoning=str(self.reasoning.titleOfSelectedItem()),
                 response_format=str(self.format.titleOfSelectedItem()), region=str(self.region.stringValue()),
                 from_language=str(self.from_language.stringValue()), to_language=str(self.to_language.stringValue()))
        p.update({key: str(view.stringValue()) for key, view in self.fields.items()})
        if self.clear_key.state():
            p["api_key"] = ""
        elif self.key.stringValue():
            p["api_key"] = str(self.key.stringValue())

    def select(self):
        index = self.provider_choice.indexOfSelectedItem()
        self.collect_provider()
        self.index = index if index >= 0 else None
        self.load_provider()

    def add(self):
        self.collect_provider()
        self.draft["providers"].append(Provider().model_dump(mode="json"))
        self.refresh_list(len(self.draft["providers"]) - 1)

    def remove(self):
        if self.index is not None:
            self.draft["providers"].pop(self.index)
        self.refresh_list()

    def reorder(self, delta):
        if self.index is None:
            return
        self.collect_provider()
        destination = max(0, min(self.index + delta, len(self.draft["providers"]) - 1))
        self.draft["providers"] = move(self.draft["providers"], self.index, destination)
        self.refresh_list(destination)

    def kind_changed(self):
        kind = self.kinds[self.kind.indexOfSelectedItem()]
        defaults = {
            "translation": ("https://api.openai.com/v1", "gpt-4o-mini", "alloy"),
            "openai_tts": ("http://localhost:8000/v1", "tts-1", "alloy"),
            "dashscope_tts": ("https://dashscope-intl.aliyuncs.com/api/v1", "qwen3-tts-flash", "Cherry"),
            "dictionary": ("https://api.cognitive.microsofttranslator.com", "", ""),
        }
        url, model, voice = defaults[kind]
        for key, value in (("endpoint", url), ("model", model), ("voice", voice)):
            self.fields[key].setStringValue_(value)

    def record(self, key):
        self.cancel_recording()
        self.recording = key
        self.app.hotkeys.stop()
        self.hotkey_buttons[key].setTitle_("请按快捷键…")
        self.window.makeFirstResponder_(None)

    def key_event(self, event):
        if not self.recording:
            return False
        if event.keyCode() == 53:
            self.cancel_recording()
            return True
        try:
            key = Hotkey(key_code=event.keyCode(), modifiers=event.modifierFlags())
        except ValueError:
            return True
        self.draft[self.recording] = key.model_dump()
        self.cancel_recording()
        return True

    def cancel_recording(self):
        if self.recording:
            key, self.recording = self.recording, None
            self.hotkey_buttons[key].setTitle_(shortcut_label(self.draft[key]))
            self.app.configure_triggers()

    def gather(self):
        self.collect_provider()
        self.draft.update({key: bool(view.state()) for key, view in self.checks.items()})
        self.draft.update(target_language=str(self.language.stringValue()), custom_prompt=str(self.prompt.string()))
        Settings.model_validate(self.draft)
        return copy.deepcopy(self.draft)

    def save(self, after=None):
        self.cancel_recording()
        try:
            body = self.gather()
        except ValueError:
            self.status.setStringValue_("设置无效：请检查地址、快捷键和必填项。")
            return
        self.save_button.setEnabled_(False)
        self.status.setStringValue_("正在保存…")

        def success(data):
            self.save_button.setEnabled_(True)
            self.draft = data
            self.app.apply_settings(Settings.model_validate(data))
            self.refresh_list()
            try:
                set_login(bool(self.login.state()))
            except Exception as exc:
                self.status.setStringValue_(str(exc))
                return
            self.status.setStringValue_("已保存")
            if after:
                after()

        def failure(exc):
            self.save_button.setEnabled_(True)
            self.status.setStringValue_(str(exc))
        self.app.request("PUT", "/settings", json=body, done=success, error=failure)

    def test(self):
        self.collect_provider()
        if self.index is None:
            return
        p = self.draft["providers"][self.index].copy()

        def test_saved():
            if p["kind"] in ("openai_tts", "dashscope_tts"):
                self.app.speak_with(p["id"], "Hello! This is a voice preview.", "en")
            else:
                self.status.setStringValue_("正在测试…")
                self.app.request("POST", f"/providers/{p['id']}/test",
                                 done=lambda _: self.status.setStringValue_("连接成功"),
                                 error=lambda e: self.status.setStringValue_(str(e)))
        self.save(after=test_saved)

    def show(self):
        self.window.makeKeyAndOrderFront_(None)
        A.NSApp.activateIgnoringOtherApps_(True)

    def close(self):
        self.cancel_recording()
        self.window.orderOut_(None)
