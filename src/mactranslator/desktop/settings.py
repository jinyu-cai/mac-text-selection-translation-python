import copy

import AppKit as A

from mactranslator.contracts import Hotkey, Provider, Settings
from mactranslator.policies import TEMPLATE, move
from mactranslator.presets import codex_cli_provider, antigravity_cli_provider, google_ai_studio_provider
from . import widgets as W
from .native import login_status, set_login
from .version import version_label


def shortcut_label(hotkey):
    flags = hotkey["modifiers"]
    prefix = "".join(symbol for flag, symbol in ((1 << 18, "⌃"), (1 << 19, "⌥"),
                                                 (1 << 17, "⇧"), (1 << 20, "⌘")) if flags & flag)
    from .keycodes import KEY_NAMES
    return prefix + KEY_NAMES.get(hotkey["key_code"], f"Key {hotkey['key_code']}")


class SettingsWindow:
    def __init__(self, app):
        self.app, self.targets = app, []
        self.window = W.window(f"Settings — {version_label()}", 850, 700)
        self.draft = app.settings.model_dump(mode="json")
        self.index = None
        self.recording = None
        root = self.window.contentView()
        tabs = A.NSTabView.alloc().initWithFrame_(A.NSMakeRect(16, 58, 818, 626))
        root.addSubview_(tabs)
        for title, build in (("General", self.build_general), ("Translation & Speech", self.build_providers)):
            tab = A.NSTabViewItem.alloc().initWithIdentifier_(title)
            tab.setLabel_(title)
            view = A.NSView.alloc().initWithFrame_(A.NSMakeRect(0, 0, 790, 580))
            tab.setView_(view)
            tabs.addTabViewItem_(tab)
            build(view)
        self.status = W.label(root, "", 20, 15, 590, 28)
        W.button(root, "Cancel", 620, 15, 90, lambda _: self.close(), self.targets)
        self.save_button = W.button(root, "Save", 730, 15, 95, lambda _: self.save(), self.targets)

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
        options = [("enable_hotkey", "Selection translation shortcut"), ("enable_ocr_hotkey", "Screenshot translation shortcut"),
                   ("enable_floating_icon", "Show floating button after selection"), ("restore_clipboard", "Restore clipboard after capture"),
                   ("enable_notes", "Enable local notes")]
        for i, (key, title) in enumerate(options):
            self.checks[key] = W.check(parent, title, 18, 536 - i * 36, 340, self.draft[key])
        self.hotkey_buttons = {}
        for key, y in (("hotkey", 534), ("ocr_hotkey", 498)):
            self.hotkey_buttons[key] = W.button(parent, shortcut_label(self.draft[key]), 385, y, 190,
                                                lambda _, key=key: self.record(key), self.targets)
        W.label(parent, "Click to record a shortcut. Esc to cancel.", 390, 459, 340)
        from ServiceManagement import SMAppServiceStatusEnabled, SMAppServiceStatusRequiresApproval
        self.login = W.check(parent, "Launch at login", 18, 349, 345,
                             login_status() in (SMAppServiceStatusEnabled, SMAppServiceStatusRequiresApproval))
        W.label(parent, "Translate to", 18, 307, 110)
        self.language = W.field(parent, 125, 305, 220, self.draft["target_language"])
        W.label(parent, "Custom prompt (optional)", 18, 259, 430)
        W.button(parent, "Use Default Template", 535, 258, 205,
                 lambda _: self.prompt.setString_(TEMPLATE), self.targets)
        self.prompt, _ = W.text_area(parent, 18, 35, 722, 218, editable=True)
        self.prompt.setString_(self.draft["custom_prompt"])

    def build_providers(self, parent):
        self.provider_choice = W.choice(parent, [], 18, 532, 726, lambda _: self.select(), self.targets)
        W.button(parent, "Add Google AI Studio", 18, 490, 194,
                 lambda _: self.add(google_ai_studio_provider()), self.targets)
        for title, x, width, action in (("Add Other", 220, 110, self.add), ("Delete", 338, 76, self.remove),
                                        ("Up", 422, 76, lambda: self.reorder(-1)),
                                        ("Down", 506, 76, lambda: self.reorder(1))):
            W.button(parent, title, x, 490, width, lambda _, action=action: action(), self.targets)
        W.button(parent, "Add Antigravity", 18, 91, 190,
                 lambda _: self.add(antigravity_cli_provider()), self.targets)
        W.button(parent, "Add Codex", 220, 91, 150,
                 lambda _: self.add(codex_cli_provider()), self.targets)
        self.enabled = W.check(parent, "Enabled", 644, 494, 100)
        self.kinds = ["translation", "gemini_cli", "antigravity_cli", "codex_cli", "openai_tts", "dashscope_tts"]
        kind_names = ["AI Translation", "Gemini CLI (legacy)", "Antigravity CLI", "Codex (ChatGPT)", "OpenAI-compatible speech", "DashScope speech"]
        if self.app.experimental:
            self.kinds.append("dictionary")
            kind_names.append("Microsoft Dictionary (experimental)")
        W.label(parent, "Type", 18, 449, 100)
        self.kind = W.choice(parent, kind_names, 128, 447, 250, lambda _: self.kind_changed(), self.targets)
        W.label(parent, "Name", 404, 449, 65)
        self.name = W.field(parent, 475, 447, 269)
        self.fields = {}
        for name, title, y in (("endpoint", "Endpoint", 403), ("model", "Model", 362)):
            W.label(parent, title, 18, y + 2, 105)
            self.fields[name] = W.field(parent, 128, y, 616)
        W.label(parent, "API Key", 18, 323, 105)
        self.key = W.field(parent, 128, 321, 402, secure=True)
        self.paste_button = W.button(parent, "Paste", 538, 319, 68, lambda _: self.paste_key(), self.targets)
        self.clear_key = W.check(parent, "Clear Key", 618, 322, 126)
        self.key_hint = W.label(parent, "Paste with ⌘V. Keys are stored securely in macOS Keychain.", 128, 287, 616)
        self.key_hint.setTextColor_(A.NSColor.secondaryLabelColor())
        self.detail_groups = {kind: [] for kind in ("translation", "gemini_cli", "tts", "dictionary")}
        group = self.detail_groups["translation"]
        group.append(W.label(parent, "Reasoning", 18, 240, 105))
        self.reasoning = W.choice(parent, ["auto", "off", "low", "medium", "high", "xhigh", "max"], 128, 237, 250)
        group.append(self.reasoning)
        group.append(W.label(parent, "Auto uses the model default. Other levels depend on model support.", 128, 202, 616))
        group = self.detail_groups["gemini_cli"]
        group.append(W.label(parent, "CLI Path", 18, 240, 105))
        self.fields["cli_path"] = W.field(parent, 128, 237, 616, "gemini")
        group.append(self.fields["cli_path"])
        group.append(W.label(parent, "Codex / Antigravity: use Account & Models below. Gemini needs Terminal login.",
                             128, 202, 616))
        from mactranslator.codex_models import EFFORTS
        self.codex_reasoning_label = W.label(parent, "Reasoning", 378, 157, 95)
        self.codex_reasoning = W.choice(parent, ["auto", *EFFORTS], 480, 153, 264)
        self.account_button = W.button(parent, "Account & Models…", 128, 153, 220,
                                       lambda _: self.open_antigravity_account(), self.targets)
        group = self.detail_groups["tts"]
        for name, title, y in (("voice", "Voice", 237), ("instructions", "Voice Style", 155)):
            group.append(W.label(parent, title, 18, y + 2, 105))
            self.fields[name] = W.field(parent, 128, y, 616)
            group.append(self.fields[name])
        group.append(W.label(parent, "Audio Format", 18, 197, 105))
        self.format = W.choice(parent, ["mp3", "opus", "aac", "flac", "wav", "pcm"], 128, 195, 250)
        group.append(self.format)
        group = self.detail_groups["dictionary"]
        group.append(W.label(parent, "Region", 18, 239, 105))
        self.region = W.field(parent, 128, 237, 250)
        group.append(self.region)
        group.append(W.label(parent, "Source", 18, 198, 105))
        self.from_language = W.field(parent, 128, 196, 180)
        group.append(self.from_language)
        group.append(W.label(parent, "Translate to", 404, 198, 100))
        self.to_language = W.field(parent, 514, 196, 230)
        group.append(self.to_language)
        self.test_button = W.button(parent, "Save & Test Connection", 18, 58, 190, lambda _: self.test(), self.targets)
        self.provider_hint = W.label(parent, "", 18, 20, 730)
        self.provider_hint.setTextColor_(A.NSColor.secondaryLabelColor())
        self.refresh_list()

    def update_provider_details(self):
        kind = self.kinds[self.kind.indexOfSelectedItem()]
        active = "gemini_cli" if kind in ("antigravity_cli", "codex_cli") else "tts" if kind in ("openai_tts", "dashscope_tts") else kind
        for group, views in self.detail_groups.items():
            for view in views:
                view.setHidden_(group != active)
        self.account_button.setHidden_(kind not in ("antigravity_cli", "codex_cli"))
        self.codex_reasoning_label.setHidden_(kind != "codex_cli")
        self.codex_reasoning.setHidden_(kind != "codex_cli")
        is_cli = kind in ("gemini_cli", "antigravity_cli", "codex_cli")
        self.fields["endpoint"].setEnabled_(not is_cli)
        self.key.setEnabled_(not is_cli)
        self.paste_button.setEnabled_(not is_cli)
        self.clear_key.setEnabled_(not is_cli)
        self.key_hint.setStringValue_("Uses your signed-in CLI account; no API key or endpoint required." if is_cli
                                      else "Paste with ⌘V. Keys are stored securely in macOS Keychain.")
        self.fields["model"].setEnabled_(kind != "dictionary")
        self.test_button.setTitle_("Save & Preview Voice" if active == "tts" else "Save & Test Connection")
        self.provider_hint.setStringValue_("Uses your CLI account quota. Available models and limits depend on your account." if is_cli
                                           else "Use a Gemini API key from Google AI Studio. Choose a model available to your account."
                                           if "generativelanguage.googleapis.com" in str(self.fields["endpoint"].stringValue())
                                           else "Add multiple services. Their order controls translation results and voice options.")

    def open_antigravity_account(self):
        if self.index is None:
            return
        self.collect_provider()
        previous = getattr(self, "account_window", None)
        if previous and not previous.closed:
            if previous.provider_id == self.draft["providers"][self.index]["id"]:
                previous.show()
                return
            previous.close()
        from .antigravity_account import AntigravityAccountWindow
        from .codex_account import CodexAccountWindow
        account_type = CodexAccountWindow if self.draft["providers"][self.index]["kind"] == "codex_cli" else AntigravityAccountWindow
        self.account_window = account_type(self)
        self.account_window.show()

    def paste_key(self):
        if self.index is None:
            self.status.setStringValue_("Add a service first.")
            return
        text = A.NSPasteboard.generalPasteboard().stringForType_(A.NSPasteboardTypeString)
        if not text or not str(text).strip():
            self.status.setStringValue_("No text on the clipboard. Copy your API key first.")
            return
        self.key.setStringValue_(str(text).strip())
        self.clear_key.setState_(0)
        self.status.setStringValue_("API key pasted. Save to apply.")

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
        self.name.setStringValue_(p["name"] if self.index is not None else "Add a service to get started")
        self.kind.selectItemAtIndex_(self.kinds.index(p["kind"]) if p["kind"] in self.kinds else 0)
        self.enabled.setState_(p["enabled"])
        for key, view in self.fields.items():
            view.setStringValue_(p.get(key, "gemini" if key == "cli_path" else ""))
        self.key.setStringValue_(p.get("api_key", ""))
        self.key.setPlaceholderString_("Saved key — leave blank to keep" if p.get("has_api_key") else "Optional for local services")
        self.clear_key.setState_(0)
        self.reasoning.selectItemWithTitle_(p["reasoning"])
        self.codex_reasoning.selectItemWithTitle_("none" if p["reasoning"] == "off" else p["reasoning"])
        self.format.selectItemWithTitle_(p["response_format"])
        self.region.setStringValue_(p["region"])
        self.from_language.setStringValue_(p["from_language"])
        self.to_language.setStringValue_(p["to_language"])
        self.test_button.setEnabled_(self.index is not None)
        self.update_provider_details()

    def collect_provider(self):
        if self.index is None:
            return
        p = self.draft["providers"][self.index]
        p.update(name=str(self.name.stringValue()), kind=self.kinds[self.kind.indexOfSelectedItem()],
                 enabled=bool(self.enabled.state()), reasoning=str((self.codex_reasoning if self.kinds[self.kind.indexOfSelectedItem()] == "codex_cli" else self.reasoning).titleOfSelectedItem()),
                 response_format=str(self.format.titleOfSelectedItem()), region=str(self.region.stringValue()),
                 from_language=str(self.from_language.stringValue()), to_language=str(self.to_language.stringValue()))
        p.update({key: str(view.stringValue()) for key, view in self.fields.items()})
        if p["kind"] in ("gemini_cli", "antigravity_cli", "codex_cli"):
            p.pop("api_key", None)
        elif self.clear_key.state():
            p["api_key"] = ""
        elif self.key.stringValue():
            p["api_key"] = str(self.key.stringValue()).strip()

    def select(self):
        index = self.provider_choice.indexOfSelectedItem()
        self.collect_provider()
        self.index = index if index >= 0 else None
        self.load_provider()

    def add(self, provider=None):
        self.collect_provider()
        self.draft["providers"].append((provider or Provider()).model_dump(mode="json"))
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
            "codex_cli": ("https://chatgpt.com", "auto", ""),
            "antigravity_cli": ("https://antigravity.google", "auto", ""),
            "gemini_cli": ("https://generativelanguage.googleapis.com", "auto", ""),
            "translation": ("https://api.openai.com/v1", "gpt-4o-mini", "alloy"),
            "openai_tts": ("http://localhost:8000/v1", "tts-1", "alloy"),
            "dashscope_tts": ("https://dashscope-intl.aliyuncs.com/api/v1", "qwen3-tts-flash", "Cherry"),
            "dictionary": ("https://api.cognitive.microsofttranslator.com", "", ""),
        }
        if kind in ("gemini_cli", "antigravity_cli", "codex_cli"):
            self.fields["cli_path"].setStringValue_("codex" if kind == "codex_cli" else "agy" if kind == "antigravity_cli" else "gemini")
        url, model, voice = defaults[kind]
        for key, value in (("endpoint", url), ("model", model), ("voice", voice)):
            self.fields[key].setStringValue_(value)
        self.reasoning.selectItemWithTitle_("auto")
        self.codex_reasoning.selectItemWithTitle_("auto")
        self.update_provider_details()

    def record(self, key):
        self.cancel_recording()
        self.recording = key
        self.app.hotkeys.stop()
        self.hotkey_buttons[key].setTitle_("Press a shortcut…")
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
            self.status.setStringValue_("Check the endpoint, shortcuts, and required fields.")
            return
        self.save_button.setEnabled_(False)
        self.status.setStringValue_("Saving…")

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
            self.status.setStringValue_("Saved")
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
                self.status.setStringValue_("Testing…")
                self.app.request("POST", f"/providers/{p['id']}/test",
                                 done=lambda _: self.status.setStringValue_("Connection successful"),
                                 error=lambda e: self.status.setStringValue_(str(e)))
        self.save(after=test_saved)

    def show(self):
        self.window.makeKeyAndOrderFront_(None)
        A.NSApp.activateIgnoringOtherApps_(True)

    def close(self):
        self.cancel_recording()
        self.window.orderOut_(None)
