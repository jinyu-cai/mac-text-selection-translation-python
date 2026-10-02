import asyncio
import concurrent.futures
import fcntl
import sys
from uuid import uuid4

import AppKit as A
import AVFoundation as AV
from Foundation import NSData, NSLinguisticTagger, NSObject
from PyObjCTools import AppHelper

from mactranslator import APP_NAME
from mactranslator.backend.storage import data_directory
from mactranslator.contracts import Settings
from mactranslator.policies import speech_text
from .native import Hotkeys, SelectionWatcher, accessibility_allowed, alert, bind, capture_selection, on_main
from .notes import NotesWindow
from .ocr import OCRCapture
from .popup import FloatingIcon, TranslationPopup
from .runtime import BackendRuntime
from .settings import SettingsWindow
from .version import version_label
from . import widgets as W


class Delegate(NSObject):
    def applicationDidFinishLaunching_(self, notification):
        self.owner.start()

    def applicationShouldTerminate_(self, application):
        self.owner.begin_quit()
        return A.NSTerminateLater


class WindowDelegate(NSObject):
    def windowShouldClose_(self, sender):
        self.callback()
        return False


class TranslatorApp:
    def __init__(self, experimental=False):
        W.install_edit_menu()
        self.experimental = experimental
        self.runtime = None
        self.settings = Settings()
        self.ready = False
        self.quitting = False
        self.pending = set()
        self.targets = []
        self.translation_task = self.capture_task = self.speech_task = self.suggestions_task = None
        self.capture_generation = 0
        self.speech_generation = 0
        self.speech_preparing = False
        self.popup = TranslationPopup(self)
        self.icon = FloatingIcon(self.translate_selection)
        self.hotkeys = Hotkeys()
        self.watcher = SelectionWatcher(self.selection_found, self.dismiss)
        self.ocr = OCRCapture()
        self.settings_window = None
        self.notes_window = None
        self.audio = None
        self.synthesizer = AV.AVSpeechSynthesizer.alloc().init()
        self.window_delegates = []
        self.set_close(self.popup.window, self.dismiss)
        self.monitor = A.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            A.NSEventMaskKeyDown | A.NSEventMaskLeftMouseDown, self.local_event)
        self.status_item = A.NSStatusBar.systemStatusBar().statusItemWithLength_(A.NSSquareStatusItemLength)
        status_button = self.status_item.button()
        image = W.symbol("textformat", "Translator")
        if image:
            image.setSize_(A.NSMakeSize(18, 18))
            status_button.setImage_(image)
        else:
            status_button.setTitle_("T")
        status_button.setToolTip_(f"{APP_NAME} — {version_label()}")
        status_button.setAccessibilityLabel_("Translator")
        self.build_menu()

    def set_close(self, window, callback):
        delegate = WindowDelegate.alloc().init()
        delegate.callback = callback
        self.window_delegates.append(delegate)
        window.setDelegate_(delegate)

    def build_menu(self):
        menu = A.NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        self.menu_actions = []
        self.ready_items = []

        def item(title, callback, requires_ready=False):
            value = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            bind(value, lambda _: callback(), self.menu_actions)
            value.setEnabled_(not requires_ready or self.ready)
            menu.addItem_(value)
            if requires_ready:
                self.ready_items.append(value)
            return value

        item(APP_NAME, lambda: None).setEnabled_(False)
        item(version_label(), lambda: None).setEnabled_(False)
        menu.addItem_(A.NSMenuItem.separatorItem())
        self.status_menu = item("Starting…", lambda: None)
        self.status_menu.setEnabled_(False)
        self.retry_item = item("Restart Service", self.start_backend)
        menu.addItem_(A.NSMenuItem.separatorItem())
        item("Translate Selection", self.translate_selection, True)
        item("Translate Clipboard", self.translate_clipboard, True)
        item("Screenshot Translation…", self.translate_ocr, True)
        self.notes_item = item("Notes…", self.open_notes, True)
        self.notes_item.setHidden_(True)
        item("Stop Speaking", self.stop_speech)
        menu.addItem_(A.NSMenuItem.separatorItem())
        item("Settings…", self.open_settings, True)
        item("Accessibility Access…", self.permission)
        item("Quit", lambda: A.NSApp.terminate_(None))
        self.status_item.setMenu_(menu)

    def start(self):
        self.start_backend()

    def start_backend(self):
        self.ready = False
        self.hotkeys.stop()
        self.watcher.stop()
        self.dismiss()
        self.retry_item.setEnabled_(False)
        for item in self.ready_items:
            item.setEnabled_(False)
        self.status_menu.setTitle_("Starting…")
        if self.runtime:
            for task in tuple(self.pending):
                task.cancel()
            self.runtime.stop()
        self.runtime = BackendRuntime(experimental=self.experimental)

        def started(future):
            try:
                future.result()
            except BaseException:
                AppHelper.callAfter(self.startup_failed)
            else:
                AppHelper.callAfter(self.load_settings)
        self.runtime.start().add_done_callback(started)

    def startup_failed(self):
        self.status_menu.setTitle_("Could not start. Please retry.")
        self.retry_item.setHidden_(False)
        self.retry_item.setEnabled_(True)
        self.popup.notice("The local service could not start. Retry from the menu bar, or launch the app from Terminal to see details.")

    def load_settings(self):
        def loaded(data):
            self.ready = True
            for item in self.ready_items:
                item.setEnabled_(True)
            self.retry_item.setEnabled_(True)
            self.retry_item.setHidden_(True)
            self.status_menu.setTitle_("Ready to Translate" + (" · Experimental" if self.experimental else ""))
            self.apply_settings(Settings.model_validate(data))
        self.request("GET", "/settings", done=loaded, error=lambda _: self.startup_failed())

    def apply_settings(self, settings):
        self.settings = settings
        self.notes_item.setHidden_(not settings.enable_notes)
        self.configure_triggers()
        if self.popup.window.isVisible():
            self.popup.render()

    def configure_triggers(self):
        if not self.ready or self.quitting:
            return
        bindings = []
        if self.settings.enable_hotkey:
            bindings.append((self.settings.hotkey, self.translate_selection))
        if self.settings.enable_ocr_hotkey:
            bindings.append((self.settings.ocr_hotkey, self.translate_ocr))
        try:
            self.hotkeys.configure(bindings)
        except Exception as exc:
            self.error(exc)
        self.watcher.start()
        if not self.settings.enable_floating_icon:
            self.icon.hide()

    def run(self, coroutine, done=None, error=None, during_quit=False):
        future = self.runtime.submit(coroutine)
        self.pending.add(future)

        def complete(f):
            def deliver():
                self.pending.discard(f)
                if self.quitting and not during_quit:
                    return
                try:
                    result = f.result()
                except (concurrent.futures.CancelledError, asyncio.CancelledError):
                    return
                except Exception as exc:
                    (error or self.error)(exc)
                else:
                    if done:
                        try:
                            done(result)
                        except Exception as exc:
                            (error or self.error)(exc)
            AppHelper.callAfter(deliver)
        future.add_done_callback(complete)
        return future

    def request(self, method, path, done=None, error=None, **kwargs):
        return self.run(self.runtime.request(method, path, **kwargs), done, error)

    def error(self, error):
        alert(str(error))

    def permission(self):
        if accessibility_allowed(True):
            alert("Accessibility access is enabled.")
        else:
            alert("Enable Text Selection Translation Python in System Settings → Privacy & Security → Accessibility, then restart the app.")

    def selection_found(self, point):
        if (self.ready and self.settings.enable_floating_icon and not self.ocr.busy
                and not (self.settings_window and self.settings_window.recording)):
            self.icon.show(point)

    def translate_selection(self, point=None):
        if not self.ready:
            return
        self.icon.hide()
        if not accessibility_allowed(True):
            self.popup.notice("Allow Accessibility access, then restart the app.", point)
            return
        self.capture_generation += 1
        generation = self.capture_generation
        if self.capture_task:
            self.capture_task.cancel()
        self.cancel_translation()
        point = point or A.NSEvent.mouseLocation()

        def captured(text):
            if generation != self.capture_generation:
                return
            if text:
                self.translate(text, point)
            else:
                self.popup.notice("No selected text found. Try again, or use Screenshot Translation.", point)
        self.capture_task = self.run(capture_selection(self.settings.restore_clipboard), done=captured)

    def translate_clipboard(self):
        self.capture_generation += 1
        if self.capture_task:
            self.capture_task.cancel()
        text = A.NSPasteboard.generalPasteboard().stringForType_(A.NSPasteboardTypeString)
        if text and str(text).strip():
            self.translate(str(text))
        else:
            self.popup.notice("No text on the clipboard.")

    def translate_ocr(self):
        if not self.ready or self.ocr.busy:
            return
        self.dismiss()
        if self.capture_task:
            self.capture_task.cancel()
        self.capture_generation += 1
        generation = self.capture_generation
        self.capture_task = self.run(self.ocr.capture(),
                                     done=lambda text: self.translate(text) if generation == self.capture_generation else None)

    def cancel_translation(self):
        if self.suggestions_task:
            self.suggestions_task.cancel()
            self.suggestions_task = None
        if self.translation_task:
            self.translation_task.cancel()
            self.translation_task = None
        self.popup.request_id = None

    def translate(self, text, point=None):
        if not self.ready:
            return
        self.cancel_translation()
        self.stop_speech()
        request_id = str(uuid4())
        self.popup.show(text, request_id, point)
        self.translation_task = self.run(
            self.runtime.stream({"request_id": request_id, "text": text},
                                lambda event: AppHelper.callAfter(self.popup.event, event)),
            error=lambda exc: self.popup.failed(request_id, exc))
        if self.settings.enable_word_suggestions and self.settings.enable_notes:
            self.suggestions_task = self.request(
                "POST", "/word-suggestions", json={"request_id": request_id, "text": text},
                done=self.popup.suggestions_done,
                error=lambda exc: self.popup.suggestions_failed(request_id, exc))

    def dismiss(self):
        if not self.ocr.busy:
            self.capture_generation += 1
            if self.capture_task:
                self.capture_task.cancel()
        self.icon.hide()
        self.popup.hide()
        self.cancel_translation()
        self.stop_speech()

    def local_event(self, event):
        if event.type() == A.NSEventTypeKeyDown:
            if self.settings_window and self.settings_window.key_event(event):
                return None
            if event.keyCode() == 53 and self.popup.window.isVisible():
                self.dismiss()
                return None
        elif event.window() not in (self.icon.window, self.popup.window):
            self.dismiss()
        return event

    def open_settings(self):
        if not self.settings_window:
            self.settings_window = SettingsWindow(self)
            self.set_close(self.settings_window.window, self.settings_window.close)
        elif not self.settings_window.window.isVisible():
            self.settings_window.reload()
        self.settings_window.show()

    def open_notes(self):
        if not self.notes_window:
            self.notes_window = NotesWindow(self)
            self.set_close(self.notes_window.window, lambda: (self.notes_window.flush(), self.notes_window.window.orderOut_(None)))
        self.notes_window.show()

    def stop_speech(self):
        self.speech_generation += 1
        self.speech_preparing = False
        self.popup.refresh_speech()
        if self.speech_task:
            self.speech_task.cancel()
        self.synthesizer.stopSpeakingAtBoundary_(AV.AVSpeechBoundaryImmediate)
        if self.audio:
            self.audio.stop()
            self.audio = None

    def speak(self, text):
        providers = [p for p in self.settings.providers if p.enabled and p.kind in ("openai_tts", "dashscope_tts")]
        if not providers:
            self.speak_native(text)
        elif len(providers) == 1:
            self.speak_with(str(providers[0].id), text)
        else:
            menu = A.NSMenu.alloc().init()
            targets = []
            for p in providers:
                item = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(p.name, None, "")
                bind(item, lambda _, p=p: self.speak_with(str(p.id), text), targets)
                menu.addItem_(item)
            menu.addItem_(A.NSMenuItem.separatorItem())
            native = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("macOS Voice", None, "")
            bind(native, lambda _: self.speak_native(text), targets)
            menu.addItem_(native)
            menu.popUpMenuPositioningItem_atLocation_inView_(None, A.NSEvent.mouseLocation(), None)

    def speak_native(self, text):
        self.stop_speech()
        text = speech_text(text)
        if not text:
            return
        utterance = AV.AVSpeechUtterance.speechUtteranceWithString_(text)
        language = NSLinguisticTagger.dominantLanguageForString_(text) or "en-US"
        voice = AV.AVSpeechSynthesisVoice.voiceWithLanguage_(language)
        if voice:
            utterance.setVoice_(voice)
        self.synthesizer.speakUtterance_(utterance)

    def speak_with(self, provider_id, text, language=None):
        if not text.strip():
            return
        self.stop_speech()
        self.speech_preparing = True
        self.popup.refresh_speech()
        language = language or NSLinguisticTagger.dominantLanguageForString_(text)
        generation = self.speech_generation

        def play(audio):
            if generation != self.speech_generation:
                return
            self.speech_preparing = False
            self.popup.refresh_speech()
            data = NSData.dataWithBytes_length_(audio, len(audio))
            player, error = AV.AVAudioPlayer.alloc().initWithData_error_(data, None)
            if player is None:
                raise RuntimeError(str(error.localizedDescription()) if error else "Could not play audio.")
            self.audio = player
            if not player.play():
                raise RuntimeError("Could not play audio. Check the audio format.")
        def failed(exc):
            if generation == self.speech_generation:
                self.speech_preparing = False
                self.popup.refresh_speech()
                self.error(exc)

        self.speech_task = self.run(self.runtime.speech({"provider_id": provider_id, "text": text, "language": language}),
                                    done=play, error=failed)

    def begin_quit(self):
        if self.quitting:
            return
        self.quitting = True
        self.hotkeys.stop()
        self.watcher.stop()
        self.dismiss()
        self.capture_generation += 1
        if self.capture_task:
            self.capture_task.cancel()
        self.ocr.cancel()
        writes = self.notes_window.flush() if self.notes_window and self.ready else []

        async def finish():
            try:
                if writes:
                    await asyncio.wait_for(asyncio.gather(*(asyncio.wrap_future(f) for f in writes)), 5)
            except Exception:
                await on_main(lambda: alert("Some notes could not be saved. Save them again before quitting."))
                await on_main(self.abort_quit)
                return
            await on_main(self.finish_quit)

        if self.runtime and self.runtime.loop and self.runtime.loop.is_running():
            self.runtime.submit(finish())
        else:
            self.finish_quit()

    def abort_quit(self):
        self.quitting = False
        self.configure_triggers()
        A.NSApp.replyToApplicationShouldTerminate_(False)

    def finish_quit(self):
        if self.monitor:
            A.NSEvent.removeMonitor_(self.monitor)
        if self.runtime and self.runtime.server:
            # Do not join from AppKit while the asyncio thread is awaiting on_main.
            self.runtime.server.should_exit = True
        A.NSApp.replyToApplicationShouldTerminate_(True)


def main():
    if sys.platform != "darwin":
        raise SystemExit("This desktop app requires macOS 14 or later.")
    if "--smoke-test" in sys.argv:
        from .smoke import run
        index = sys.argv.index("--smoke-test")
        if index + 1 >= len(sys.argv):
            raise SystemExit("Usage: --smoke-test OUTPUT_DIRECTORY")
        run(sys.argv[index + 1], TranslatorApp)
        return
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    lock = (directory / "desktop.lock").open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("The Python translator is already running.")
    application = A.NSApplication.sharedApplication()
    application.setActivationPolicy_(A.NSApplicationActivationPolicyAccessory)
    owner = TranslatorApp(experimental="--experimental-dictionary" in sys.argv)
    delegate = Delegate.alloc().init()
    delegate.owner = owner
    application.setDelegate_(delegate)
    try:
        AppHelper.runEventLoop()
    finally:
        if owner.runtime:
            owner.runtime.stop()
        lock.close()


if __name__ == "__main__":
    main()
